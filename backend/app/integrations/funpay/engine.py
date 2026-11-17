"""Чаты, заказы и лоты FunPay через библиотеку funpaybotengine (MIT).

Новые сообщения находим так же, как FunPay Hub: опрашиваем превью чатов
и сравниваем last_message_id с запомненным. При первом опросе только
запоминаем текущие id, чтобы бот не отвечал на старую переписку.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from funpaybotengine import Bot

from app.core.timing import logged_call
from app.integrations.funpay.base import (
    BaseLotRaiser,
    BaseMarketplace,
    IncomingChat,
    LotDetails,
    MarketplaceAuthError,
    MarketplaceError,
    RaiseResult,
)
from app.models.domain import (
    Author,
    Channel,
    ChatMessage,
    Offer,
    OpenOrder,
)

log = logging.getLogger('funpay.chat')
OFFERS_TTL_SEC = 120


@dataclass
class FunPayMarketplace(BaseMarketplace, BaseLotRaiser):
    golden_key: str
    user_agent: str
    subcategories: list[int]
    channel: Channel = Channel.FUNPAY
    _bot: Bot | None = field(default=None, init=False)
    _seen: dict[str, int] = field(default_factory=dict, init=False)
    _baseline_done: bool = field(default=False, init=False)
    _offers_cache: tuple[float, list[Offer]] = field(
        default=(0.0, []),
        init=False,
    )

    async def _client(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(
                golden_key=self.golden_key,
                default_headers={'User-Agent': self.user_agent},
            )
            try:
                await self._bot.update()
            except Exception as e:
                self._bot = None
                log.warning('FunPay: вход по golden_key не удался: %s', e)
                raise MarketplaceAuthError(str(e)) from e
            log.info('FunPay: вошли как %s', self._bot.username)
        return self._bot

    async def fetch_new_messages(self) -> list[IncomingChat]:
        bot = await self._client()
        async with logged_call(log, 'FunPay: превью чатов', logging.DEBUG):
            previews = await bot.get_recent_chat_previews()
        if not self._baseline_done:
            self._seen = {str(p.id): p.last_message_id for p in previews}
            self._baseline_done = True
            return []
        result = []
        for p in previews:
            chat_id = str(p.id)
            seen = self._seen.get(chat_id, 0)
            if p.last_message_id <= seen:
                continue
            msgs = await bot.get_chat_messages(
                chat_id=p.id,
                after_message_id=seen or None,
            )
            self._seen[chat_id] = p.last_message_id
            incoming = self._convert(chat_id, p.username, msgs, bot.userid)
            if incoming.messages:
                result.append(incoming)
                log.info(
                    'FunPay: %d новых сообщений в чате %s (%s)',
                    len(incoming.messages),
                    chat_id,
                    p.username,
                    extra={'chat_id': chat_id},
                )
        return result

    @staticmethod
    def _convert(
        chat_id: str,
        username: str,
        msgs: list,
        own_id: int,
    ) -> IncomingChat:
        chat = IncomingChat(
            chat_id=chat_id, buyer_id=None, buyer_name=username
        )
        now = datetime.now(timezone.utc)
        for m in msgs:
            if m.sender_id == own_id:
                author = Author.SELLER
            elif m.sender_id:
                author = Author.BUYER
                chat.buyer_id = m.sender_id
            else:
                author = Author.SYSTEM
            chat.messages.append(
                ChatMessage(
                    channel=Channel.FUNPAY,
                    chat_id=chat_id,
                    message_id=m.id,
                    author=author,
                    text=m.text or ('[картинка]' if m.image_url else ''),
                    created_at=now,
                    buyer_id=chat.buyer_id,
                    buyer_name=username,
                ),
            )
        return chat

    async def last_message_id(self, chat_id: str) -> int:
        bot = await self._client()
        async with logged_call(
            log, f'FunPay: история чата {chat_id}', logging.DEBUG
        ):
            msgs = await bot.get_chat_messages(chat_id=int(chat_id))
        return max((m.id for m in msgs), default=0)

    async def send(self, chat_id: str, text: str) -> ChatMessage:
        bot = await self._client()
        async with logged_call(log, f'FunPay: отправка в чат {chat_id}'):
            msg = await bot.send_message(int(chat_id), text=text)
        self._seen[chat_id] = max(self._seen.get(chat_id, 0), msg.id)
        return ChatMessage(
            channel=Channel.FUNPAY,
            chat_id=chat_id,
            message_id=msg.id,
            author=Author.BOT,
            text=text,
            created_at=datetime.now(timezone.utc),
        )

    async def open_orders(self, buyer_id: int | None) -> list[OpenOrder]:
        bot = await self._client()
        async with logged_call(log, 'FunPay: открытые заказы'):
            batch = await bot.get_sales(status_filter='paid')
        return [
            OpenOrder(
                order_id=o.id,
                title=o.title,
                price=float(o.total.value),
                buyer_id=o.counterparty.id,
                buyer_name=o.counterparty.username,
            )
            for o in batch.orders
            if buyer_id is None or o.counterparty.id == buyer_id
        ]

    async def offers(self) -> list[Offer]:
        cached_at, cached = self._offers_cache
        if time.monotonic() - cached_at < OFFERS_TTL_SEC and cached:
            return cached
        bot = await self._client()
        result = []
        for sub in self.subcategories:
            try:
                page = await bot.get_my_offers_page(sub)
            except Exception as e:  # чужая/пустая подкатегория
                log.warning('Лоты подкатегории %s: %s', sub, e)
                continue
            for offer in page.offers.values():
                result.append(
                    Offer(
                        offer_id=str(offer.id),
                        title=offer.title or '',
                        price=float(offer.price.value),
                        amount=offer.amount,
                        category=str(sub),
                        auto_delivery=offer.auto_delivery,
                    ),
                )
        self._offers_cache = (time.monotonic(), result)
        return result

    async def lot_details(self, lot_id: str) -> LotDetails | None:
        bot = await self._client()
        async with logged_call(log, f'FunPay: карточка лота {lot_id}'):
            fields = await bot.get_offer_fields(offer_id=int(lot_id))
        goods = fields.secrets or []
        return LotDetails(
            title=fields.title_ru or '',
            description=fields.desc_ru or '',
            auto_delivery=bool(fields.auto_delivery),
            goods_count=len(goods),
        )

    async def add_auto_delivery(self, lot_id: str, items: list[str]) -> int:
        """Дописывает товары в автовыдачу лота на FunPay.

        Сами строки (логины, пароли) не логируются и нигде у нас не
        сохраняются — только число.
        """
        bot = await self._client()
        async with logged_call(log, f'FunPay: автовыдача лота {lot_id}'):
            fields = await bot.get_offer_fields(offer_id=int(lot_id))
            current = [g for g in fields.secrets or [] if g.strip()]
            fields.secrets = current + items
            fields.auto_delivery = True
            saved = await bot.save_offer_fields(fields)
        if not saved:
            raise MarketplaceError('FunPay не сохранил лот')
        total = len(current) + len(items)
        log.info(
            'FunPay: в автовыдачу лота %s добавлено %d, всего %d',
            lot_id,
            len(items),
            total,
        )
        return total

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
