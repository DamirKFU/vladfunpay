from abc import ABC, abstractmethod
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


class BaseUserRepository(ABC):
    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def get(self, username: str) -> User | None: ...

    @abstractmethod
    async def list(self) -> list[User]: ...

    @abstractmethod
    async def save(self, user: User) -> None: ...

    @abstractmethod
    async def delete(self, username: str) -> None: ...


class BaseSettingsRepository(ABC):
    """Хранит настройки как dict (секреты уже зашифрованы)."""

    @abstractmethod
    async def load(self) -> dict[str, Any]: ...

    @abstractmethod
    async def save(self, data: dict[str, Any]) -> None: ...


class BaseOrderRepository(ABC):
    @abstractmethod
    async def upsert_many(self, orders: list[Order]) -> int: ...

    @abstractmethod
    async def get(self, order_uid: str) -> Order | None: ...

    @abstractmethod
    async def list_all(self) -> list[Order]: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def max_paid_at(self) -> datetime | None: ...

    @abstractmethod
    async def min_paid_at(self, status: str) -> datetime | None: ...

    @abstractmethod
    async def by_buyer(self, buyer_id: int) -> list[Order]: ...

    @abstractmethod
    async def set_steam(
        self,
        order_uid: str,
        link: str,
        steam_id: str | None,
    ) -> None: ...

    @abstractmethod
    async def node_ids(self) -> list[int]: ...

    @abstractmethod
    async def game_ids(self) -> list[int]:
        """Категории FunPay (игры), где были продажи: raw.game.game_id."""


class BaseSyncRunRepository(ABC):
    @abstractmethod
    async def save(self, run: SyncRun) -> None: ...

    @abstractmethod
    async def latest(self, limit: int) -> list[SyncRun]: ...


class BaseLogRepository(ABC):
    @abstractmethod
    async def insert_many(self, entries: list[LogEntry]) -> None: ...

    @abstractmethod
    async def query(
        self,
        level: str | None,
        source: str | None,
        search: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[LogEntry]: ...

    @abstractmethod
    async def sources(self) -> list[str]: ...


class BaseSteamRepository(ABC):
    @abstractmethod
    async def save_snapshot(
        self,
        friends: list[SteamFriend],
        own_level: int | None,
        refreshed_at: datetime,
    ) -> None: ...

    @abstractmethod
    async def load_snapshot(
        self,
    ) -> tuple[list[SteamFriend], int | None, datetime | None]: ...

    @abstractmethod
    async def cached_levels(
        self,
        steam_ids: list[str],
        newer_than: datetime,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def cache_levels(
        self,
        levels: dict[str, int],
        at: datetime,
    ) -> None: ...


class BaseSteamLinkRepository(ABC):
    @abstractmethod
    async def list(self, channel: str) -> list[SteamLinkRecord]: ...


class BaseSalesSnapshotRepository(ABC):
    @abstractmethod
    async def load(self) -> SalesSnapshot | None: ...

    @abstractmethod
    async def save(self, snapshot: SalesSnapshot) -> None: ...
