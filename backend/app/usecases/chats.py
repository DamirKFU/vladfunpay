"""Переписка бота, ассортимент и тестовая песочница."""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core import messages
from app.integrations.funpay.sandbox import SandboxMarketplace
from app.models.domain import (
    BotTrace,
    Channel,
    ChatMessage,
    Conversation,
    Offer,
    OpenOrder,
)
from app.repositories.base import BaseChatRepository, BaseSandboxRepository
from app.usecases.errors import NotFoundError, ValidationError
from app.usecases.lots import LotCatalogService

SANDBOX_BUYER_BASE = 900_000_000


@dataclass(frozen=True)
class ChatView:
    conversation: Conversation
    messages: list[ChatMessage]
    traces: list[BotTrace]


@dataclass(frozen=True)
class ChatService:
    chats: BaseChatRepository

    async def conversations(self, channel: Channel) -> list[Conversation]:
        return await self.chats.conversations(channel, 200)

    async def view(self, channel: Channel, chat_id: str) -> ChatView:
        conv = await self.chats.get_conversation(channel, chat_id)
        if conv is None:
            raise NotFoundError(
                messages.SANDBOX_CHAT_NOT_FOUND.format(chat_id)
            )
        return ChatView(
            conversation=conv,
            messages=await self.chats.messages(channel, chat_id, 200),
            traces=await self.chats.traces(channel, chat_id, 50),
        )

    async def resume(self, channel: Channel, chat_id: str) -> None:
        """Вернуть чат боту после передачи продавцу."""
        conv = await self.chats.get_conversation(channel, chat_id)
        if conv is None:
            raise NotFoundError(
                messages.SANDBOX_CHAT_NOT_FOUND.format(chat_id)
            )
        conv.needs_human = False
        conv.human_reason = ''
        await self.chats.save_conversation(conv)


@dataclass(frozen=True)
class SandboxService:
    """Покупатели, лоты и заказы песочницы + сообщения от имени покупателя."""

    marketplace: SandboxMarketplace
    sandbox: BaseSandboxRepository
    chats: BaseChatRepository
    catalog: LotCatalogService

    async def create_chat(self, buyer_name: str) -> Conversation:
        buyer_name = buyer_name.strip() or 'test_buyer'
        number = await self.sandbox.next_id('buyer')
        conv = Conversation(
            channel=Channel.SANDBOX,
            chat_id=f'sandbox-{number}',
            buyer_id=SANDBOX_BUYER_BASE + number,
            buyer_name=buyer_name,
            last_message_at=datetime.now(timezone.utc),
        )
        await self.chats.save_conversation(conv)
        return conv

    async def say(self, chat_id: str, text: str) -> ChatMessage:
        if not text.strip():
            raise ValidationError('пустое сообщение')
        conv = await self._conv(chat_id)
        return await self.marketplace.buyer_says(
            chat_id,
            conv.buyer_id or 0,
            conv.buyer_name,
            text.strip(),
        )

    async def reset(self, chat_id: str) -> None:
        conv = await self._conv(chat_id)
        await self.chats.clear(Channel.SANDBOX, chat_id)
        conv.last_answered_id = 0
        conv.needs_human = False
        conv.replies_today = 0
        await self.chats.save_conversation(conv)

    async def create_order(
        self,
        chat_id: str,
        offer_id: str | None,
        title: str,
        price: float,
    ) -> OpenOrder:
        conv = await self._conv(chat_id)
        if offer_id:
            offer = next(
                (
                    o
                    for o in await self.sandbox.offers()
                    if o.offer_id == offer_id
                ),
                None,
            )
            if offer is None:
                raise NotFoundError(
                    messages.SANDBOX_OFFER_NOT_FOUND.format(offer_id),
                )
            title, price = offer.title, offer.price
            if offer.amount is not None:
                offer.amount = max(0, offer.amount - 1)
                await self.sandbox.save_offer(offer)
        number = await self.sandbox.next_id('order')
        order = OpenOrder(
            order_id=f'TEST{number:04d}',
            title=title or 'Тестовый товар',
            price=price,
            buyer_id=conv.buyer_id,
            buyer_name=conv.buyer_name,
            created_at=datetime.now(timezone.utc),
        )
        await self.sandbox.save_order(order)
        return order

    async def set_order_status(self, order_id: str, status: str) -> None:
        for order in await self.sandbox.orders(None):
            if order.order_id == order_id:
                order.status = status
                await self.sandbox.save_order(order)
                return
        raise NotFoundError(messages.ORDER_NOT_FOUND.format(order_id))

    async def orders(self, chat_id: str | None) -> list[OpenOrder]:
        if chat_id is None:
            return await self.sandbox.orders(None)
        conv = await self._conv(chat_id)
        return await self.sandbox.orders(conv.buyer_id)

    async def offers(self) -> list[Offer]:
        return await self.sandbox.offers()

    async def save_offer(self, offer: Offer) -> Offer:
        if not offer.offer_id:
            offer.offer_id = f'lot{await self.sandbox.next_id("offer")}'
        await self.sandbox.save_offer(offer)
        # Лот сразу попадает в каталог и получает тип (как после
        # синхронизации с FunPay).
        await self.catalog.sync(Channel.SANDBOX)
        return offer

    async def delete_offer(self, offer_id: str) -> None:
        await self.sandbox.delete_offer(offer_id)
        await self.catalog.sync(Channel.SANDBOX)

    async def friendship(self, chat_id: str) -> dict:
        conv = await self._conv(chat_id)
        stored = await self.sandbox.friendship(conv.buyer_id or 0)
        relationship, since = stored or (None, None)
        return {'relationship': relationship, 'since': since}

    async def set_friendship(
        self,
        chat_id: str,
        relationship: str | None,
        since: datetime | None,
    ) -> dict:
        """Симуляция: как будто покупатель в друзьях Steam с даты since."""
        conv = await self._conv(chat_id)
        if relationship == 'friend' and since is None:
            since = datetime.now(timezone.utc)
        await self.sandbox.set_friendship(
            conv.buyer_id or 0,
            relationship,
            since if relationship == 'friend' else None,
        )
        return await self.friendship(chat_id)

    async def _conv(self, chat_id: str) -> Conversation:
        conv = await self.chats.get_conversation(Channel.SANDBOX, chat_id)
        if conv is None:
            raise NotFoundError(
                messages.SANDBOX_CHAT_NOT_FOUND.format(chat_id)
            )
        return conv
