import logging
from dataclasses import dataclass, field

from funpaybotengine import Bot
from funpaybotengine.types import OrderPreview
from funpaybotengine.types.enums import OrderStatus

from app.core.timing import logged_call
from app.integrations.funpay.base import (
    BaseLotRaiser,
    MarketplaceAuthError,
    MarketplaceError,
    RaiseResult,
    SalesReader,
)
from app.models.domain import SalePreview

log = logging.getLogger('funpay')
MAX_PAID_PAGES = 100


@dataclass
class FunPayMarketplace(SalesReader, BaseLotRaiser):
    golden_key: str
    user_agent: str
    _bot: Bot | None = field(default=None, init=False)

    async def _client(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(
                golden_key=self.golden_key,
                default_headers={'User-Agent': self.user_agent},
            )
            try:
                await self._bot.update()
            except Exception as e:
                await self.close()
                log.warning('FunPay: вход по golden_key не удался: %s', e)
                raise MarketplaceAuthError(str(e)) from e
            log.info('FunPay: вошли как %s', self._bot.username)
        return self._bot

    async def sales(self) -> list[SalePreview]:
        bot = await self._client()
        async with logged_call(log, 'FunPay: открытые и последние заказы'):
            orders = await self._paid_sales(bot)
            recent = await bot.get_sales()
        orders.update((order.id, order) for order in recent.orders)
        return [
            SalePreview(
                order_id=order.id,
                title=order.title,
                buyer_name=order.counterparty.username,
                price=float(order.total.value),
                currency=order.total.character,
                status=funpay_status(order.status),
                date_text=order.date_text,
            )
            for order in orders.values()
        ]

    @staticmethod
    async def _paid_sales(bot: Bot) -> dict[str, OrderPreview]:
        orders: dict[str, OrderPreview] = {}
        seen_cursors: set[str] = set()
        cursor = None
        for _ in range(MAX_PAID_PAGES):
            page = await bot.get_sales(
                from_order_id=cursor,
                status_filter=OrderStatus.PAID,
            )
            orders.update((order.id, order) for order in page.orders)
            cursor = page.next_order_id
            if not cursor:
                return orders
            if cursor in seen_cursors:
                raise MarketplaceError('FunPay повторил страницу заказов')
            seen_cursors.add(cursor)
        raise MarketplaceError('Превышен лимит страниц открытых заказов')

    async def raise_lots(self, category_id: int) -> RaiseResult:
        bot = await self._client()
        async with logged_call(log, f'FunPay: поднятие лотов {category_id}'):
            resp = await bot.raise_offers(category_id)
        result = RaiseResult(
            ok=not resp.error,
            message=resp.msg or '',
            wait_sec=int(resp.wait or 0),
        )
        log.log(
            logging.INFO if result.ok else logging.WARNING,
            'FunPay: поднятие категории %s: %s (ждать %d с)',
            category_id,
            result.message or ('готово' if result.ok else 'ошибка'),
            result.wait_sec,
        )
        return result

    async def close(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
            except MarketplaceError:
                pass
            self._bot = None


STATUS_MAP = {'PAID': 'paid', 'COMPLETED': 'closed', 'REFUNDED': 'refunded'}


def funpay_status(status: object) -> str:
    """OrderStatus FunPay (PAID/COMPLETED/REFUNDED) -> paid/closed/refunded."""
    raw = str(getattr(status, 'value', status) or '').upper()
    return STATUS_MAP.get(raw, raw.lower() or 'unknown')
