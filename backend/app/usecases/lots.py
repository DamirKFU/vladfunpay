"""Каталог лотов: карточки с площадки, тип товара, аккаунты в автовыдачу."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.bot.catalog import (
    classification_messages,
    match_keywords,
    order_type,
    parse_classification,
    type_by_id,
)
from app.integrations.funpay.base import BaseMarketplace, MarketplaceError
from app.integrations.funpay.sandbox import SandboxMarketplace
from app.integrations.llm.base import LLMError
from app.integrations.provider import BaseIntegrations, NotConfiguredError
from app.models.app_settings import AppSettings, ProductKind, ProductType
from app.models.domain import Channel, LotRecord, OpenOrder
from app.repositories.base import (
    BaseLotRepository,
    BaseOrderRepository,
    BaseUsageRepository,
)
from app.usecases.errors import (
    ExternalServiceError,
    NotFoundError,
    ValidationError,
)
from app.usecases.settings import SettingsService

log = logging.getLogger('lots')
MSK = ZoneInfo('Europe/Moscow')
CLASSIFY_MAX_TOKENS = 200
ACCOUNT_FIELDS = (
    ('login', 'Логин'),
    ('password', 'Пароль'),
    ('email', 'Почта'),
    ('email_password', 'Пароль почты'),
    ('note', 'Примечание'),
)


def account_line(account: dict[str, str]) -> str:
    """Один аккаунт = одна строка автовыдачи FunPay."""
    parts = []
    for key, label in ACCOUNT_FIELDS:
        value = ' '.join(str(account.get(key) or '').split())
        if value:
            parts.append(f'{label}: {value}')
    return ' | '.join(parts)


@dataclass(frozen=True)
class LotCatalogService:
    settings: SettingsService
    lots: BaseLotRepository
    orders: BaseOrderRepository
    usage: BaseUsageRepository
    integrations: BaseIntegrations
    sandbox: SandboxMarketplace

    async def all_lots(self, channel: Channel) -> list[LotRecord]:
        return await self.lots.list(channel)

    async def sync(self, channel: Channel) -> list[LotRecord]:
        """Забирает лоты и описания карточек, определяет тип новых."""
        s = await self.settings.get()
        market = await self._market(channel, s)
        try:
            offers = await market.offers()
            seen = set()
            for offer in offers:
                seen.add(offer.offer_id)
                await self._sync_one(channel, market, offer, s)
        except MarketplaceError as e:
            raise ExternalServiceError(str(e)) from e
        finally:
            if channel == Channel.FUNPAY:
                await market.close()
        for lot in await self.lots.list(channel):
            if lot.lot_id not in seen:
                await self.lots.delete(channel, lot.lot_id)
                log.info('Лот %s больше не на площадке, убран', lot.title)
        result = await self.lots.list(channel)
        log.info('Лоты %s синхронизированы: %d', channel, len(result))
        return result

    async def _sync_one(self, channel, market, offer, s) -> None:  # noqa: ANN001
        old = await self.lots.get(channel, offer.offer_id)
        try:
            details = await market.lot_details(offer.offer_id)
        except Exception as e:  # карточка не открылась — берём что есть
            log.warning('Карточка лота %s: %s', offer.offer_id, e)
            details = None
        lot = LotRecord(
            channel=channel,
            lot_id=offer.offer_id,
            title=(
                details.title if details and details.title else offer.title
            ),
            description=details.description
            if details
            else (offer.description or (old.description if old else '')),
            type_id=old.type_id if old else '',
            assigned_by=old.assigned_by if old else '',
            amount=offer.amount,
            auto_delivery=(
                details.auto_delivery if details else offer.auto_delivery
            ),
            price=offer.price,
            updated_at=datetime.now(timezone.utc),
        )
        changed = old is None or (old.title, old.description) != (
            lot.title,
            lot.description,
        )
        # Тип пересчитываем, если карточка изменилась или тип был угадан
        # дёшево (слова/по умолчанию): вдруг поменялись типы в настройках.
        # Ручной выбор не трогаем, решение ИИ — только при изменении.
        cheap = lot.assigned_by in ('', 'default', 'keywords')
        if lot.assigned_by != 'manual' and (changed or cheap):
            lot = await self._classify(lot, s)
        await self.lots.save(lot)

    async def set_type(
        self,
        channel: Channel,
        lot_id: str,
        type_id: str | None,
    ) -> LotRecord:
        """Ручной выбор типа. None — снова определять автоматически."""
        s = await self.settings.get()
        lot = await self._lot(channel, lot_id)
        if type_id is None:
            lot = await self._classify(replace(lot, assigned_by=''), s)
        else:
            if type_id not in {t.id for t in s.catalog.types}:
                raise ValidationError(f'нет типа товара {type_id}')
            lot = replace(lot, type_id=type_id, assigned_by='manual')
        await self.lots.save(lot)
        log.info(
            'Тип лота «%s»: %s (%s)', lot.title, lot.type_id, lot.assigned_by
        )
        return lot

    async def _classify(self, lot: LotRecord, s: AppSettings) -> LotRecord:
        catalog = s.catalog
        hit = match_keywords(catalog, lot.title, lot.description)
        if hit:
            return replace(lot, type_id=hit.id, assigned_by='keywords')
        if catalog.classify_with_ai and lot.description.strip():
            result = await self._classify_ai(lot, s)
            if result:
                return replace(lot, type_id=result, assigned_by='ai')
        return replace(
            lot,
            type_id=type_by_id(catalog, catalog.default_type).id,
            assigned_by='default',
        )

    async def _classify_ai(self, lot: LotRecord, s: AppSettings) -> str | None:
        try:
            llm = self.integrations.llm(s)
            reply = await llm.complete(
                classification_messages(s.catalog, lot.title, lot.description),
                [],
                CLASSIFY_MAX_TOKENS,
            )
        except (NotConfiguredError, LLMError) as e:
            log.info('ИИ-классификация лота «%s» пропущена: %s', lot.title, e)
            return None
        day = datetime.now(MSK).date().isoformat()
        await self.usage.add_tokens(day, reply.tokens)
        parsed = parse_classification(s.catalog, reply.content)
        if parsed is None:
            log.warning(
                'ИИ вернул непонятный тип для «%s»: %s',
                lot.title,
                reply.content[:200],
            )
            return None
        type_id, reason = parsed
        log.info(
            'ИИ определил тип «%s» → %s: %s',
            lot.title,
            type_id,
            reason,
            extra={'tokens': reply.tokens},
        )
        return type_id

    async def add_accounts(
        self,
        channel: Channel,
        lot_id: str,
        accounts: list[dict[str, str]],
    ) -> LotRecord:
        """Аккаунты — сразу в автовыдачу площадки, у нас не хранятся."""
        lot = await self._lot(channel, lot_id)
        lines = []
        for account in accounts:
            if not (account.get('login') and account.get('password')):
                raise ValidationError(
                    'у каждого аккаунта нужны логин и пароль'
                )
            lines.append(account_line(account))
        if not lines:
            raise ValidationError('нет аккаунтов')
        s = await self.settings.get()
        if type_by_id(s.catalog, lot.type_id).kind != ProductKind.ACCOUNT:
            log.warning(
                'Аккаунты добавляются в лот «%s» не типа «аккаунт»', lot.title
            )
        market = await self._market(channel, s)
        try:
            total = await market.add_auto_delivery(lot_id, lines)
        except MarketplaceError as e:
            raise ExternalServiceError(str(e)) from e
        finally:
            if channel == Channel.FUNPAY:
                await market.close()
        lot = replace(lot, amount=total, auto_delivery=True)
        await self.lots.save(lot)
        log.info(
            'В автовыдачу «%s» добавлено аккаунтов: %d (всего %d)',
            lot.title,
            len(lines),
            total,
        )
        return lot

    async def order_types(
        self,
        channel: Channel,
        orders: list[OpenOrder],
        s: AppSettings,
    ) -> dict[str, ProductType]:
        lots = await self.lots.list(channel)
        return {
            o.order_id: order_type(s.catalog, o.title, lots) for o in orders
        }

    async def _lot(self, channel: Channel, lot_id: str) -> LotRecord:
        lot = await self.lots.get(channel, lot_id)
        if lot is None:
            raise NotFoundError(f'лот {lot_id} не найден, синхронизируйте')
        return lot

    async def _market(
        self,
        channel: Channel,
        s: AppSettings,
    ) -> BaseMarketplace:
        if channel == Channel.SANDBOX:
            return self.sandbox
        try:
            return self.integrations.funpay(s, await self.orders.node_ids())
        except NotConfiguredError as e:
            raise ValidationError(str(e)) from e
