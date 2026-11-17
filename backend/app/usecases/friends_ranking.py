"""Кого из друзей Steam можно удалить, когда кончаются слоты.

Порядок важности (сверху — удалять последними или никогда):
1. защищённые вручную (список в админке) — не удаляются;
2. покупатели с открытым заказом — не удаляются;
3. покупатели, которые давно в друзьях (дольше long_friend_days),
   свежие покупки выше;
4. недавние покупатели;
5. просто друзья — по уровню Steam, выше уровень — важнее;
6. исходящие заявки в друзья — старые удаляются первыми.

Исходящие заявки тоже занимают слоты, входящие — нет (их не считаем).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.integrations.steam.base import friend_limit
from app.models.domain import (
    FriendsReport,
    FriendTier,
    RankedFriend,
    Relationship,
    SteamFriend,
)

TIER_ORDER = [
    FriendTier.PROTECTED,
    FriendTier.OPEN_ORDER,
    FriendTier.LONG_BUYER,
    FriendTier.BUYER,
    FriendTier.FRIEND,
    FriendTier.INVITE,
]
NOT_REMOVABLE = {FriendTier.PROTECTED, FriendTier.OPEN_ORDER}
REASONS = {
    FriendTier.PROTECTED: 'в защищённом списке',
    FriendTier.OPEN_ORDER: 'есть открытый заказ',
    FriendTier.LONG_BUYER: 'покупатель, давно в друзьях',
    FriendTier.BUYER: 'покупатель',
    FriendTier.FRIEND: 'просто друг',
    FriendTier.INVITE: 'ожидающая заявка',
}


@dataclass(frozen=True)
class BuyerInfo:
    name: str
    orders: int
    last_order_at: datetime | None
    has_open_order: bool


def _tier(
    friend: SteamFriend,
    protected: set[str],
    buyer: BuyerInfo | None,
    long_since: datetime,
) -> FriendTier:
    if friend.steam_id in protected:
        return FriendTier.PROTECTED
    if buyer and buyer.has_open_order:
        return FriendTier.OPEN_ORDER
    if friend.relationship != Relationship.FRIEND:
        return FriendTier.INVITE
    if buyer:
        since = friend.friend_since
        if since and since <= long_since:
            return FriendTier.LONG_BUYER
        return FriendTier.BUYER
    return FriendTier.FRIEND


def _ts(value: datetime | None) -> float:
    return value.timestamp() if value else 0.0


def _sort_key(item: RankedFriend) -> tuple:
    f = item.friend
    tier = TIER_ORDER.index(item.tier)
    if item.tier in (FriendTier.LONG_BUYER, FriendTier.BUYER):
        return tier, -_ts(item.last_order_at), _ts(f.friend_since)
    if item.tier == FriendTier.FRIEND:
        level = f.level if f.level is not None else -1
        return tier, -level, _ts(f.friend_since)
    if item.tier == FriendTier.INVITE:
        return tier, -_ts(f.friend_since)
    return tier, _ts(f.friend_since)


def rank_friends(
    friends: list[SteamFriend],
    protected: set[str],
    buyers: dict[str, BuyerInfo],
    now: datetime,
    long_friend_days: int,
    own_level: int | None,
    keep_free: int,
    refreshed_at: datetime | None = None,
) -> FriendsReport:
    long_since = now - timedelta(days=long_friend_days)
    ranked = []
    for friend in friends:
        buyer = buyers.get(friend.steam_id)
        tier = _tier(friend, protected, buyer, long_since)
        ranked.append(
            RankedFriend(
                friend=friend,
                tier=tier,
                rank=0,
                removable=tier not in NOT_REMOVABLE,
                reason=REASONS[tier],
                buyer_name=buyer.name if buyer else '',
                last_order_at=buyer.last_order_at if buyer else None,
                orders=buyer.orders if buyer else 0,
            ),
        )
    ranked.sort(key=_sort_key)
    for i, item in enumerate(ranked, 1):
        item.rank = i

    used = sum(
        1 for f in friends if f.relationship != Relationship.INVITE_RECEIVED
    )
    limit = friend_limit(own_level)
    to_free = max(0, used - (limit - keep_free)) if limit else 0
    removable = [
        r
        for r in reversed(ranked)
        if r.removable
        and r.friend.relationship != Relationship.INVITE_RECEIVED
    ]
    return FriendsReport(
        own_level=own_level,
        limit=limit,
        used=used,
        keep_free=keep_free,
        to_free=to_free,
        ranked=ranked,
        candidates=removable[:to_free],
        refreshed_at=refreshed_at,
    )
