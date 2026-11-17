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
    """Продажа FunPay в виде, удобном для статистики и бота."""

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


class Author(StrEnum):
    BUYER = 'buyer'
    BOT = 'bot'
    SELLER = 'seller'
    SYSTEM = 'system'


class Channel(StrEnum):
    FUNPAY = 'funpay'
    SANDBOX = 'sandbox'


@dataclass
class ChatMessage:
    channel: Channel
    chat_id: str
    message_id: int
    author: Author
    text: str
    created_at: datetime
    buyer_id: int | None = None
    buyer_name: str = ''


@dataclass
class Conversation:
    channel: Channel
    chat_id: str
    buyer_id: int | None
    buyer_name: str
    last_message_at: datetime
    last_answered_id: int = 0
    needs_human: bool = False
    human_reason: str = ''
    replies_day: str = ''
    replies_today: int = 0


@dataclass
class ToolCallTrace:
    name: str
    arguments: dict[str, Any]
    result: Any


@dataclass
class BotTrace:
    channel: Channel
    chat_id: str
    created_at: datetime
    input_text: str
    reply: str | None
    outcome: str  # replied / template / skipped / discarded / error
    detail: str = ''
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    tokens: int = 0


@dataclass
class OpenOrder:
    order_id: str
    title: str
    price: float
    buyer_id: int | None
    buyer_name: str
    status: str = 'paid'
    created_at: datetime | None = None


@dataclass
class Offer:
    offer_id: str
    title: str
    price: float
    amount: int | None
    category: str = ''
    auto_delivery: bool = False
    description: str = ''


class Relationship(StrEnum):
    FRIEND = 'friend'
    INVITE_SENT = 'invite_sent'
    INVITE_RECEIVED = 'invite_received'


@dataclass
class SteamFriend:
    steam_id: str
    relationship: Relationship
    name: str = ''
    level: int | None = None
    friend_since: datetime | None = None
    avatar: str = ''


class FriendTier(StrEnum):
    """Важность друга: чем меньше номер, тем позже его можно удалить."""

    PROTECTED = 'protected'
    OPEN_ORDER = 'open_order'
    LONG_BUYER = 'long_buyer'
    BUYER = 'buyer'
    FRIEND = 'friend'
    INVITE = 'invite'


@dataclass
class RankedFriend:
    friend: SteamFriend
    tier: FriendTier
    rank: int
    removable: bool
    reason: str
    buyer_name: str = ''
    last_order_at: datetime | None = None
    orders: int = 0


@dataclass
class FriendsReport:
    own_level: int | None
    limit: int | None
    used: int
    keep_free: int
    to_free: int
    ranked: list[RankedFriend]
    candidates: list[RankedFriend]
    refreshed_at: datetime | None


@dataclass
class SteamLinkRecord:
    channel: Channel
    order_id: str
    buyer_id: int | None
    buyer_name: str
    link: str
    steam_id: str | None
    saved_at: datetime


@dataclass
class LotRecord:
    """Лот в каталоге: карточка FunPay (или песочницы) и её тип товара."""

    channel: Channel
    lot_id: str
    title: str
    description: str = ''
    type_id: str = ''
    assigned_by: str = ''  # manual / keywords / ai / default
    amount: int | None = None
    auto_delivery: bool = False
    price: float = 0.0
    updated_at: datetime | None = None
