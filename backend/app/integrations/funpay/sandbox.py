"""Песочница: площадка для проверки бота из фронта, без FunPay.

Сообщения покупателя кладёт API (/api/sandbox/...), бот забирает их тем
же циклом, что и на FunPay, и отвечает через тот же конвейер с ИИ.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.integrations.funpay.base import (
    BaseMarketplace,
    IncomingChat,
    LotDetails,
    MarketplaceError,
)
from app.models.domain import Author, Channel, ChatMessage, Offer, OpenOrder
from app.repositories.base import BaseChatRepository, BaseSandboxRepository


@dataclass
class SandboxMarketplace(BaseMarketplace):
    chats: BaseChatRepository
    sandbox: BaseSandboxRepository
    channel: Channel = Channel.SANDBOX
    _pending: dict[str, IncomingChat] = field(
        default_factory=dict,
        init=False,
    )

    async def buyer_says(
        self,
        chat_id: str,
        buyer_id: int,
        buyer_name: str,
        text: str,
    ) -> ChatMessage:
        message = ChatMessage(
            channel=Channel.SANDBOX,
            chat_id=chat_id,
            message_id=await self.sandbox.next_id('message'),
            author=Author.BUYER,
            text=text,
            created_at=datetime.now(timezone.utc),
            buyer_id=buyer_id,
            buyer_name=buyer_name,
        )
        await self.chats.add_message(message)
        chat = self._pending.setdefault(
            chat_id,
            IncomingChat(
                chat_id=chat_id,
                buyer_id=buyer_id,
                buyer_name=buyer_name,
            ),
        )
        chat.messages.append(message)
        return message

    async def fetch_new_messages(self) -> list[IncomingChat]:
        pending = list(self._pending.values())
        self._pending.clear()
        return pending

    async def last_message_id(self, chat_id: str) -> int:
        msgs = await self.chats.messages(Channel.SANDBOX, chat_id, 1)
        return msgs[-1].message_id if msgs else 0

    async def send(self, chat_id: str, text: str) -> ChatMessage:
        message = ChatMessage(
            channel=Channel.SANDBOX,
            chat_id=chat_id,
            message_id=await self.sandbox.next_id('message'),
            author=Author.BOT,
            text=text,
            created_at=datetime.now(timezone.utc),
        )
        await self.chats.add_message(message)
        return message

    async def open_orders(self, buyer_id: int | None) -> list[OpenOrder]:
        orders = await self.sandbox.orders(buyer_id)
        return [o for o in orders if o.status == 'paid']

    async def offers(self) -> list[Offer]:
        return await self.sandbox.offers()

    async def lot_details(self, lot_id: str) -> LotDetails | None:
        for offer in await self.sandbox.offers():
            if offer.offer_id == lot_id:
                return LotDetails(
                    title=offer.title,
                    description=offer.description,
                    auto_delivery=offer.auto_delivery,
                    goods_count=offer.amount,
                )
        return None

    async def add_auto_delivery(self, lot_id: str, items: list[str]) -> int:
        """В песочнице данные не сохраняются: только растёт количество."""
        for offer in await self.sandbox.offers():
            if offer.offer_id == lot_id:
                offer.amount = (offer.amount or 0) + len(items)
                offer.auto_delivery = True
                await self.sandbox.save_offer(offer)
                return offer.amount
        raise MarketplaceError(f'лот {lot_id} не найден')
