"""HTML-отчёт по продажам (шаблон из legacy/report_template.html)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.models.domain import Order

TEMPLATE = Path(__file__).with_name('template.html')
DATA_MARKER = '/*__DATA__*/null'
MSK = ZoneInfo('Europe/Moscow')


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(MSK).isoformat(timespec='seconds')


def to_row(order: Order) -> dict[str, Any]:
    raw = order.raw or {}
    review = raw.get('review') or {}
    type_data = raw.get('type_data') or {}
    return {
        'id': order.order_uid,
        'game': order.game,
        'cat': order.category,
        'qty': type_data.get('amount'),
        'auto': bool(type_data.get('auto_delivery')),
        'price': order.amount,
        'cur': order.currency,
        'status': order.status,
        'created': _iso(order.created_at),
        'paid': _iso(order.paid_at),
        'closed': _iso(order.closed_at),
        'refunded': _iso(order.refunded_at),
        'buyer_id': order.buyer_id,
        'buyer': order.buyer_name,
        'rating': order.rating,
        'review': order.review_text,
        'reply': bool(review.get('reply')),
    }


def render_report(orders: list[Order]) -> str:
    payload = {
        'generated': datetime.now(MSK).isoformat(timespec='seconds'),
        'source': 'база',
        'orders': [to_row(o) for o in orders],
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    data = (
        data.replace('</', r'<\/')
        .replace('\u2028', '\u2028')
        .replace('\u2029', '\u2029')
    )
    return TEMPLATE.read_text(encoding='utf-8').replace(DATA_MARKER, data)
