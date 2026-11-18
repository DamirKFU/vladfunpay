from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.models.domain import SalePreview


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


class SalesReader(ABC):
    @abstractmethod
    async def sales(self) -> list[SalePreview]: ...

    async def close(self) -> None:
        return None
