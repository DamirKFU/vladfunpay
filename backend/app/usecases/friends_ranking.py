"""Приоритет друзей Steam на основе покупок и срока дружбы."""

from dataclasses import dataclass
from datetime import datetime

from app.integrations.steam.base import friend_limit
from app.models.domain import (
    FriendsReport,
    FriendTier,
    RankedFriend,
    Relationship,
    SteamFriend,
)


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
) -> FriendTier:
    if friend.relationship != Relationship.FRIEND:
        return FriendTier.INVITE
    if friend.steam_id in protected:
        return FriendTier.PROTECTED
    if buyer and buyer.has_open_order:
        return FriendTier.OPEN_ORDER
    if buyer:
        return FriendTier.BUYER
    return FriendTier.FRIEND


def _ts(value: datetime | None) -> float:
    return value.timestamp() if value else 0.0


def _sort_key(item: RankedFriend) -> tuple[int, float, float, str]:
    groups = {
        FriendTier.PROTECTED: 0,
        FriendTier.OPEN_ORDER: 1,
        FriendTier.BUYER: 2,
        FriendTier.FRIEND: 2,
        FriendTier.INVITE: 3,
    }
    return (
        groups[item.tier],
        -_ts(item.last_order_at),
        -_ts(item.friend.friend_since),
        item.friend.steam_id,
    )


def rank_friends(
    friends: list[SteamFriend],
    protected: set[str],
    buyers: dict[str, BuyerInfo],
    own_level: int | None,
    refreshed_at: datetime | None = None,
) -> FriendsReport:
    ranked = []
    for friend in friends:
        buyer = buyers.get(friend.steam_id)
        tier = _tier(friend, protected, buyer)
        ranked.append(
            RankedFriend(
                friend=friend,
                tier=tier,
                rank=0,
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
    return FriendsReport(
        own_level=own_level,
        limit=limit,
        used=used,
        ranked=ranked,
        refreshed_at=refreshed_at,
    )
