from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.integrations.funpay.base import (
    BaseLotRaiser,
    BaseOrderExporter,
    RaiseResult,
)
from app.integrations.funpay.orders import parse_dt


@dataclass
class MemoryOrderExporter(BaseOrderExporter):
    """Выгрузка из заранее заданных записей (формат как у FunPay)."""

    records: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[date | None, date]] = field(default_factory=list)

    async def export(
        self,
        date_from: date | None,
        date_to: date,
    ) -> list[dict[str, Any]]:
        self.calls.append((date_from, date_to))
        result = []
        for rec in self.records:
            paid = parse_dt(rec.get('paid_at'))
            day = paid.date() if paid else None
            if day is None:
                continue
            if date_from and day < date_from:
                continue
            if day > date_to:
                continue
            result.append(rec)
        return result


@dataclass
class MemoryLotRaiser(BaseLotRaiser):
    """Поднятие лотов в памяти: отвечает заданным результатом."""

    result: RaiseResult = field(
        default_factory=lambda: RaiseResult(
            True, 'Предложения подняты', 14400
        ),
    )
    calls: list[int] = field(default_factory=list)

    async def raise_lots(self, category_id: int) -> RaiseResult:
        self.calls.append(category_id)
        return self.result
