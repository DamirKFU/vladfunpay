import copy
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.models.domain import (
    LogEntry,
    Order,
    SalesSnapshot,
    SteamFriend,
    SteamLinkRecord,
    SyncRun,
    User,
)
from app.repositories.base import (
    BaseLogRepository,
    BaseOrderRepository,
    BaseSalesSnapshotRepository,
    BaseSettingsRepository,
    BaseSteamLinkRepository,
    BaseSteamRepository,
    BaseSyncRunRepository,
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
class MemorySteamLinkRepository(BaseSteamLinkRepository):
    _items: dict[tuple[str, str], SteamLinkRecord] = field(
        default_factory=dict,
        kw_only=True,
    )

    async def list(self, channel: str) -> list[SteamLinkRecord]:
        return [r for (ch, _), r in self._items.items() if ch == str(channel)]


@dataclass
class MemorySalesSnapshotRepository(BaseSalesSnapshotRepository):
    _snapshot: SalesSnapshot | None = field(default=None, init=False)

    async def load(self) -> SalesSnapshot | None:
        return copy.deepcopy(self._snapshot)

    async def save(self, snapshot: SalesSnapshot) -> None:
        self._snapshot = copy.deepcopy(snapshot)
