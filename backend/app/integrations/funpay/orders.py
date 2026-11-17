from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.steam.links import parse_steam_link
from app.models.domain import Order


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace('Z', '+00:00')
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_amount(value: Any) -> float:
    try:
        return float(Decimal(str(value).replace(',', '.')))
    except (InvalidOperation, ValueError):
        return 0.0


def order_from_export(rec: dict[str, Any]) -> Order:
    """Строка выгрузки orders_seller (JSONL) -> Order.

    Ключи проверены по реальной выгрузке: order_uid, game.name,
    type_data.node, buyer, amount, *_at, status, review, type_data.player.
    """
    review = rec.get('review') or {}
    player = _get(rec, 'type_data', 'player') or ''
    link = parse_steam_link(player) if player else None
    return Order(
        order_uid=str(rec['order_uid']),
        status=str(rec.get('status') or ''),
        amount=parse_amount(rec.get('amount')),
        currency=str(rec.get('currency') or 'RUB'),
        game=_get(rec, 'game', 'name') or '—',
        category=_get(rec, 'type_data', 'node', 'name') or '—',
        node_id=_get(rec, 'type_data', 'node', 'node_id'),
        buyer_id=_get(rec, 'buyer', 'user_id'),
        buyer_name=_get(rec, 'buyer', 'name') or '—',
        paid_at=parse_dt(rec.get('paid_at')),
        created_at=parse_dt(rec.get('created_at')),
        closed_at=parse_dt(rec.get('closed_at')),
        refunded_at=parse_dt(
            rec.get('refunded_at') or rec.get('partially_refunded_at'),
        ),
        rating=review.get('rating'),
        review_text=review.get('text'),
        steam_link=link.url if link else None,
        steam_id=link.steam_id if link else None,
        raw=rec,
    )
