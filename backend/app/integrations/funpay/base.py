from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models.domain import Channel, ChatMessage, Offer, OpenOrder


class MarketplaceError(RuntimeError):
    pass


class MarketplaceAuthError(MarketplaceError):
    pass


class BaseOrderExporter(ABC):
    """Выгрузка продаж за период (оплачено с/по). None = за всё время."""

    @abstractmethod
    async def export(
        self,
        date_from: date | None,
        date_to: date,
    ) -> list[dict[str, Any]]: ...


@dataclass
class IncomingChat:
    chat_id: str
    buyer_id: int | None
    buyer_name: str
    messages: list[ChatMessage] = field(default_factory=list)


class BaseMarketplace(ABC):
    """Площадка, где бот переписывается с покупателями.

    Реализации: FunPay (настоящая) и песочница во фронте. Бот работает с
    обеими одинаково, поэтому в песочнице видно реальное поведение.
    """

    channel: Channel

    @abstractmethod
    async def fetch_new_messages(self) -> list[IncomingChat]: ...

    @abstractmethod
    async def last_message_id(self, chat_id: str) -> int: ...

    @abstractmethod
    async def send(self, chat_id: str, text: str) -> ChatMessage: ...

    @abstractmethod
    async def open_orders(self, buyer_id: int | None) -> list[OpenOrder]: ...

    @abstractmethod
    async def offers(self) -> list[Offer]: ...

    async def lot_details(self, lot_id: str) -> 'LotDetails | None':
        """Карточка лота: описание и автовыдача. None — недоступно."""
        return None

    async def add_auto_delivery(self, lot_id: str, items: list[str]) -> int:
        """Добавить товары в автовыдачу лота. Возвращает, сколько их там.

        Данные (например, аккаунты) уходят на площадку и у нас не
        сохраняются.
        """
        raise MarketplaceError('автовыдача на этой площадке недоступна')

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class LotDetails:
    title: str
    description: str
    auto_delivery: bool
    goods_count: int | None


@dataclass(frozen=True)
class RaiseResult:
    ok: bool
    message: str
    wait_sec: int = 0  # через сколько можно поднимать снова


class BaseLotRaiser(ABC):
    """Кнопка «Поднять предложения» в категории (игре) FunPay."""

    @abstractmethod
    async def raise_lots(self, category_id: int) -> RaiseResult: ...

    async def close(self) -> None:
        return None
