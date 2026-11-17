"""Как и когда покупатель получит предмет — по типу товара.

Подарок: дарить можно через friend_days дней дружбы в Steam, а продавец
отправляет не больше per_day подарков в день. Поэтому дата считается
расписанием: заказы встают в очередь по дате, когда их можно дарить, и
занимают дневные слоты; если на день уже per_day подарков — переезжают
на следующий. Всё приблизительно, бот так и говорит.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.integrations.steam.friendship import Friendship
from app.integrations.steam.links import SteamLink
from app.models.app_settings import ProductKind, ProductType
from app.models.domain import OpenOrder, Relationship

MSK = ZoneInfo('Europe/Moscow')
STALE_FRIENDS_HOURS = 24

ASK_PROFILE = (
    'Steam profile link: https://steamcommunity.com/profiles/<17 digits> '
    'or https://steamcommunity.com/id/<name>'
)
ASK_TRADE = (
    'Steam trade offer link with token: '
    'https://steamcommunity.com/tradeoffer/new/?partner=...&token=... '
    '(Steam → Inventory → Trade offers → Who can send me trade offers)'
)


@dataclass(frozen=True)
class DeliveryPlan:
    order: OpenOrder
    ptype: ProductType
    status: str
    ready_at: datetime | None  # подарок: когда Steam разрешит дарить
    info: dict


def _fmt(dt: datetime | None) -> str | None:
    return dt.astimezone(MSK).strftime('%Y-%m-%d %H:%M MSK') if dt else None


def _base(order: OpenOrder, ptype: ProductType) -> dict:
    return {
        'order_id': order.order_id,
        'product_type': ptype.name,
        'method': ptype.kind,
    }


def plan_gift(
    order: OpenOrder,
    ptype: ProductType,
    link: SteamLink | None,
    friendship: Friendship,
    now: datetime,
) -> DeliveryPlan:
    info = _base(order, ptype) | {
        'friend_days_required': ptype.friend_days,
        'gifts_per_day': ptype.per_day,
    }
    if friendship.checked_at is None or (
        now - friendship.checked_at > timedelta(hours=STALE_FRIENDS_HOURS)
    ):
        info['friend_list_may_be_outdated'] = True
    if link is None or not link.steam_id:
        info |= {'status': 'need_steam_profile', 'ask_buyer_for': ASK_PROFILE}
        return DeliveryPlan(order, ptype, info['status'], None, info)

    rel = friendship.relationship
    if rel == Relationship.FRIEND and friendship.since:
        ready_at = friendship.since + timedelta(days=ptype.friend_days)
        info['friends_since'] = _fmt(friendship.since)
        info['can_gift_from'] = _fmt(ready_at)
        if ready_at <= now:
            info['status'] = 'ready_to_send'
        else:
            info['status'] = 'waiting_friendship_period'
            info['days_left'] = math.ceil(
                (ready_at - now).total_seconds() / 86400,
            )
        return DeliveryPlan(order, ptype, info['status'], ready_at, info)

    if rel == Relationship.INVITE_SENT:
        info['status'] = 'waiting_buyer_to_accept_friend_request'
    elif rel == Relationship.INVITE_RECEIVED:
        info['status'] = 'seller_will_accept_buyer_friend_request'
    else:
        info['status'] = 'not_friends_yet'
    info['earliest_if_friends_today'] = _fmt(
        now + timedelta(days=ptype.friend_days),
    )
    return DeliveryPlan(order, ptype, info['status'], None, info)


def plan_trade(
    order: OpenOrder,
    ptype: ProductType,
    link: SteamLink | None,
    now: datetime,
) -> DeliveryPlan:
    info = _base(order, ptype) | {'eta_hours': ptype.send_hours}
    if link is None or not link.trade_token:
        info |= {'status': 'need_trade_link', 'ask_buyer_for': ASK_TRADE}
        return DeliveryPlan(order, ptype, info['status'], None, info)
    info['status'] = 'waiting_trade'
    info['estimated_delivery_by'] = _fmt(
        (order.created_at or now) + timedelta(hours=ptype.send_hours),
    )
    return DeliveryPlan(order, ptype, info['status'], None, info)


def plan_account(order: OpenOrder, ptype: ProductType) -> DeliveryPlan:
    info = _base(order, ptype) | {
        'status': 'delivered_automatically_by_funpay',
        'where': 'the account data is in the FunPay order right after '
        'payment; never repeat it in chat',
        'login_problems': 'call request_human',
    }
    return DeliveryPlan(order, ptype, info['status'], None, info)


def plan_manual(
    order: OpenOrder,
    ptype: ProductType,
    now: datetime,
) -> DeliveryPlan:
    info = _base(order, ptype) | {'status': 'in_progress'}
    if ptype.send_hours:
        info['estimated_delivery_by'] = _fmt(
            (order.created_at or now) + timedelta(hours=ptype.send_hours),
        )
    return DeliveryPlan(order, ptype, info['status'], None, info)


def plan_delivery(
    order: OpenOrder,
    ptype: ProductType,
    link: SteamLink | None,
    friendship: Friendship,
    now: datetime,
) -> DeliveryPlan:
    if ptype.kind == ProductKind.GIFT:
        return plan_gift(order, ptype, link, friendship, now)
    if ptype.kind == ProductKind.TRADE:
        return plan_trade(order, ptype, link, now)
    if ptype.kind == ProductKind.ACCOUNT:
        return plan_account(order, ptype)
    return plan_manual(order, ptype, now)


def schedule_gifts(
    plans: list[DeliveryPlan],
    now: datetime,
) -> dict[str, dict]:
    """Очередь подарков с лимитом в день, отдельно для каждого типа.

    Возвращает order_id -> место, день отправки. Заказы без даты (нет
    ссылки или дружбы) стоят в конце без дня отправки.
    """
    result: dict[str, dict] = {}
    by_type: dict[str, list[DeliveryPlan]] = {}
    for plan in plans:
        if plan.ptype.kind == ProductKind.GIFT:
            by_type.setdefault(plan.ptype.id, []).append(plan)
    today = now.astimezone(MSK).date()
    for gifts in by_type.values():
        per_day = max(1, gifts[0].ptype.per_day)
        dated = sorted(
            (p for p in gifts if p.ready_at),
            key=lambda p: p.ready_at,
        )
        undated = [p for p in gifts if not p.ready_at]
        used: dict[date, int] = {}
        for position, plan in enumerate(dated, 1):
            day = max(plan.ready_at.astimezone(MSK).date(), today)
            while used.get(day, 0) >= per_day:
                day += timedelta(days=1)
            used[day] = used.get(day, 0) + 1
            result[plan.order.order_id] = {
                'position': position,
                'open_gift_orders': len(gifts),
                'gifts_per_day': per_day,
                'estimated_send_date': day.isoformat(),
                'days_until_send': (day - today).days,
                'approximate': True,
            }
        for position, plan in enumerate(undated, len(dated) + 1):
            result[plan.order.order_id] = {
                'position': position,
                'open_gift_orders': len(gifts),
                'gifts_per_day': per_day,
                'estimated_send_date': None,
                'approximate': True,
            }
    return result
