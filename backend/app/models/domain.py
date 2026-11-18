from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


@dataclass
class User:
    username: str
    password_hash: str
    created_at: datetime


@dataclass
class Order:
    """Продажа FunPay в виде, удобном для статистики."""

    order_uid: str
    status: str  # paid / closed / refunded
    amount: float
    currency: str
    game: str
    category: str
    node_id: int | None
    buyer_id: int | None
    buyer_name: str
    paid_at: datetime | None
    created_at: datetime | None = None
    closed_at: datetime | None = None
    refunded_at: datetime | None = None
    rating: int | None = None
    review_text: str | None = None
    steam_link: str | None = None
    steam_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SyncStatus(StrEnum):
    RUNNING = 'running'
    DONE = 'done'
    ERROR = 'error'


@dataclass
class SyncRun:
    id: str
    status: SyncStatus
    started_at: datetime
    date_from: str | None
    date_to: str
    finished_at: datetime | None = None
    fetched: int = 0
    upserted: int = 0
    message: str = ''


@dataclass
class LogEntry:
    ts: datetime
    level: str
    source: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


class Relationship(StrEnum):
    FRIEND = 'friend'
    INVITE_SENT = 'invite_sent'
    INVITE_RECEIVED = 'invite_received'


@dataclass
class SteamFriend:
    steam_id: str
    relationship: Relationship
    name: str = ''
    friend_since: datetime | None = None
    avatar: str = ''


class FriendTier(StrEnum):
    PROTECTED = 'protected'
    OPEN_ORDER = 'open_order'
    BUYER = 'buyer'
    FRIEND = 'friend'
    INVITE = 'invite'


@dataclass
class RankedFriend:
    friend: SteamFriend
    tier: FriendTier
    rank: int
    buyer_name: str = ''
    last_order_at: datetime | None = None
    orders: int = 0


@dataclass
class FriendsReport:
    own_level: int | None
    limit: int | None
    used: int
    ranked: list[RankedFriend]
    refreshed_at: datetime | None


@dataclass
class SteamLinkRecord:
    channel: str
    order_id: str
    buyer_id: int | None
    buyer_name: str
    link: str
    steam_id: str | None
    saved_at: datetime


@dataclass(frozen=True)
class SalePreview:
    order_id: str
    title: str
    buyer_name: str
    price: float
    currency: str
    status: str
    date_text: str


@dataclass(frozen=True)
class SalesSnapshot:
    refreshed_at: datetime
    items: list[SalePreview]
