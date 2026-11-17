import copy
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.models.domain import (
    BotTrace,
    Channel,
    ChatMessage,
    Conversation,
    LogEntry,
    LotRecord,
    Offer,
    OpenOrder,
    Order,
    SteamFriend,
    SteamLinkRecord,
    SyncRun,
    User,
)
from app.repositories.base import (
    BaseChatRepository,
    BaseLogRepository,
    BaseLotRepository,
    BaseOrderRepository,
    BaseSandboxRepository,
    BaseSettingsRepository,
    BaseSteamLinkRepository,
    BaseSteamRepository,
    BaseSyncRunRepository,
    BaseUsageRepository,
    BaseUserRepository,
)


@dataclass
class MemoryUserRepository(BaseUserRepository):
    _users: dict[str, User] = field(default_factory=dict, kw_only=True)

    async def count(self) -> int:
        return len(self._users)

    async def get(self, username: str) -> User | None:
        return self._users.get(username)

    async def list(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.created_at)

    async def save(self, user: User) -> None:
        self._users[user.username] = user

    async def delete(self, username: str) -> None:
        self._users.pop(username, None)


@dataclass
class MemorySettingsRepository(BaseSettingsRepository):
    _data: dict[str, Any] = field(default_factory=dict, kw_only=True)

    async def load(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    async def save(self, data: dict[str, Any]) -> None:
        self._data = copy.deepcopy(data)


@dataclass
class MemoryOrderRepository(BaseOrderRepository):
    _orders: dict[str, Order] = field(default_factory=dict, kw_only=True)

    async def upsert_many(self, orders: list[Order]) -> int:
        for order in orders:
            old = self._orders.get(order.order_uid)
            if old and old.steam_id and not order.steam_id:
                order = replace(
                    order,
                    steam_id=old.steam_id,
                    steam_link=old.steam_link,
                )
            self._orders[order.order_uid] = order
        return len(orders)

    async def get(self, order_uid: str) -> Order | None:
        return self._orders.get(order_uid)

    async def list_all(self) -> list[Order]:
        return sorted(
            self._orders.values(),
            key=lambda o: o.paid_at or datetime.min.astimezone(),
        )

    async def count(self) -> int:
        return len(self._orders)

    async def max_paid_at(self) -> datetime | None:
        dates = [o.paid_at for o in self._orders.values() if o.paid_at]
        return max(dates, default=None)

    async def min_paid_at(self, status: str) -> datetime | None:
        dates = [
            o.paid_at
            for o in self._orders.values()
            if o.paid_at and o.status == status
        ]
        return min(dates, default=None)

    async def by_buyer(self, buyer_id: int) -> list[Order]:
        return [o for o in self._orders.values() if o.buyer_id == buyer_id]

    async def set_steam(
        self,
        order_uid: str,
        link: str,
        steam_id: str | None,
    ) -> None:
        order = self._orders.get(order_uid)
        if order:
            self._orders[order_uid] = replace(
                order,
                steam_link=link,
                steam_id=steam_id,
            )

    async def node_ids(self) -> list[int]:
        return sorted(
            {o.node_id for o in self._orders.values() if o.node_id},
        )

    async def game_ids(self) -> list[int]:
        ids = {
            (o.raw.get('game') or {}).get('game_id')
            for o in self._orders.values()
        }
        return sorted(i for i in ids if i)


@dataclass
class MemorySyncRunRepository(BaseSyncRunRepository):
    _runs: dict[str, SyncRun] = field(default_factory=dict, kw_only=True)

    async def save(self, run: SyncRun) -> None:
        self._runs[run.id] = replace(run)

    async def latest(self, limit: int) -> list[SyncRun]:
        runs = list(self._runs.values())
        order = sorted(
            range(len(runs)),
            key=lambda i: (runs[i].started_at, i),
            reverse=True,
        )
        return [runs[i] for i in order][:limit]


@dataclass
class MemoryLogRepository(BaseLogRepository):
    _entries: list[LogEntry] = field(default_factory=list, kw_only=True)

    async def insert_many(self, entries: list[LogEntry]) -> None:
        self._entries.extend(entries)

    async def query(
        self,
        level: str | None,
        source: str | None,
        search: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[LogEntry]:
        result = []
        for e in reversed(self._entries):
            if level and e.level != level:
                continue
            if source and e.source != source:
                continue
            if search and search.lower() not in e.message.lower():
                continue
            if since and e.ts < since:
                continue
            result.append(e)
            if len(result) >= limit:
                break
        return result

    async def sources(self) -> list[str]:
        return sorted({e.source for e in self._entries})


def _key(channel: Channel, chat_id: str) -> tuple[str, str]:
    return str(channel), chat_id


@dataclass
class MemoryChatRepository(BaseChatRepository):
    _messages: dict[tuple[str, str], list[ChatMessage]] = field(
        default_factory=lambda: defaultdict(list),
        kw_only=True,
    )
    _conversations: dict[tuple[str, str], Conversation] = field(
        default_factory=dict,
        kw_only=True,
    )
    _traces: list[BotTrace] = field(default_factory=list, kw_only=True)

    async def add_message(self, message: ChatMessage) -> None:
        bucket = self._messages[_key(message.channel, message.chat_id)]
        if any(m.message_id == message.message_id for m in bucket):
            return
        bucket.append(message)

    async def messages(
        self,
        channel: Channel,
        chat_id: str,
        limit: int,
    ) -> list[ChatMessage]:
        bucket = sorted(
            self._messages[_key(channel, chat_id)],
            key=lambda m: m.message_id,
        )
        return bucket[-limit:]

    async def get_conversation(
        self,
        channel: Channel,
        chat_id: str,
    ) -> Conversation | None:
        conv = self._conversations.get(_key(channel, chat_id))
        return replace(conv) if conv else None

    async def save_conversation(self, conversation: Conversation) -> None:
        key = _key(conversation.channel, conversation.chat_id)
        self._conversations[key] = replace(conversation)

    async def conversations(
        self,
        channel: Channel,
        limit: int,
    ) -> list[Conversation]:
        items = [
            c
            for (ch, _), c in self._conversations.items()
            if ch == str(channel)
        ]
        items.sort(key=lambda c: c.last_message_at, reverse=True)
        return items[:limit]

    async def add_trace(self, trace: BotTrace) -> None:
        self._traces.append(trace)

    async def traces(
        self,
        channel: Channel,
        chat_id: str | None,
        limit: int,
    ) -> list[BotTrace]:
        items = [
            t
            for t in reversed(self._traces)
            if t.channel == channel
            and (chat_id is None or t.chat_id == chat_id)
        ]
        return items[:limit]

    async def clear(self, channel: Channel, chat_id: str) -> None:
        key = _key(channel, chat_id)
        self._messages.pop(key, None)
        self._conversations.pop(key, None)
        self._traces = [
            t
            for t in self._traces
            if not (t.channel == channel and t.chat_id == chat_id)
        ]


@dataclass
class MemoryUsageRepository(BaseUsageRepository):
    _days: dict[str, int] = field(
        default_factory=lambda: defaultdict(int),
        kw_only=True,
    )

    async def add_tokens(self, day: str, tokens: int) -> int:
        self._days[day] += tokens
        return self._days[day]

    async def tokens(self, day: str) -> int:
        return self._days.get(day, 0)


@dataclass
class MemorySteamRepository(BaseSteamRepository):
    _friends: list[SteamFriend] = field(default_factory=list, kw_only=True)
    _own_level: int | None = field(default=None, kw_only=True)
    _refreshed_at: datetime | None = field(default=None, kw_only=True)
    _levels: dict[str, tuple[int, datetime]] = field(
        default_factory=dict,
        kw_only=True,
    )

    async def save_snapshot(
        self,
        friends: list[SteamFriend],
        own_level: int | None,
        refreshed_at: datetime,
    ) -> None:
        self._friends = [replace(f) for f in friends]
        self._own_level = own_level
        self._refreshed_at = refreshed_at

    async def load_snapshot(
        self,
    ) -> tuple[list[SteamFriend], int | None, datetime | None]:
        return (
            [replace(f) for f in self._friends],
            self._own_level,
            self._refreshed_at,
        )

    async def remove_from_snapshot(self, steam_id: str) -> None:
        self._friends = [f for f in self._friends if f.steam_id != steam_id]

    async def cached_levels(
        self,
        steam_ids: list[str],
        newer_than: datetime,
    ) -> dict[str, int]:
        return {
            sid: level
            for sid, (level, at) in self._levels.items()
            if sid in steam_ids and at >= newer_than
        }

    async def cache_levels(
        self,
        levels: dict[str, int],
        at: datetime,
    ) -> None:
        for sid, level in levels.items():
            self._levels[sid] = (level, at)


@dataclass
class MemorySandboxRepository(BaseSandboxRepository):
    _offers: dict[str, Offer] = field(default_factory=dict, kw_only=True)
    _orders: dict[str, OpenOrder] = field(default_factory=dict, kw_only=True)
    _counters: dict[str, int] = field(
        default_factory=lambda: defaultdict(int),
        kw_only=True,
    )
    _friends: dict[int, tuple[str | None, datetime | None]] = field(
        default_factory=dict,
        kw_only=True,
    )

    async def offers(self) -> list[Offer]:
        return list(self._offers.values())

    async def save_offer(self, offer: Offer) -> None:
        self._offers[offer.offer_id] = replace(offer)

    async def delete_offer(self, offer_id: str) -> None:
        self._offers.pop(offer_id, None)

    async def orders(self, buyer_id: int | None) -> list[OpenOrder]:
        return [
            replace(o)
            for o in self._orders.values()
            if buyer_id is None or o.buyer_id == buyer_id
        ]

    async def save_order(self, order: OpenOrder) -> None:
        self._orders[order.order_id] = replace(order)

    async def next_id(self, kind: str) -> int:
        self._counters[kind] += 1
        return self._counters[kind]

    async def friendship(
        self,
        buyer_id: int,
    ) -> tuple[str | None, datetime | None] | None:
        return self._friends.get(buyer_id)

    async def set_friendship(
        self,
        buyer_id: int,
        relationship: str | None,
        since: datetime | None,
    ) -> None:
        self._friends[buyer_id] = (relationship, since)


@dataclass
class MemorySteamLinkRepository(BaseSteamLinkRepository):
    _items: dict[tuple[str, str], SteamLinkRecord] = field(
        default_factory=dict,
        kw_only=True,
    )

    async def save(self, record: SteamLinkRecord) -> None:
        self._items[(str(record.channel), record.order_id)] = record

    async def list(self, channel: Channel) -> list[SteamLinkRecord]:
        return [r for (ch, _), r in self._items.items() if ch == str(channel)]


@dataclass
class MemoryLotRepository(BaseLotRepository):
    _lots: dict[tuple[str, str], LotRecord] = field(
        default_factory=dict,
        kw_only=True,
    )

    async def list(self, channel: Channel) -> list[LotRecord]:
        return [
            replace(lot)
            for (ch, _), lot in self._lots.items()
            if ch == str(channel)
        ]

    async def get(self, channel: Channel, lot_id: str) -> LotRecord | None:
        lot = self._lots.get((str(channel), lot_id))
        return replace(lot) if lot else None

    async def save(self, lot: LotRecord) -> None:
        self._lots[(str(lot.channel), lot.lot_id)] = replace(lot)

    async def delete(self, channel: Channel, lot_id: str) -> None:
        self._lots.pop((str(channel), lot_id), None)
