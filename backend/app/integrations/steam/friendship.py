"""С какого дня покупатель у продавца в друзьях Steam.

Нужно для подарков: Steam разрешает дарить только тем, кто в друзьях
не меньше N дней (для Dota 2 — 30). Реальный источник — последний снимок
друзей из Steam; в песочнице дружба задаётся во фронте вручную.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.models.domain import Relationship
from app.repositories.base import BaseSandboxRepository, BaseSteamRepository


@dataclass(frozen=True)
class Friendship:
    relationship: Relationship | None  # None — не в друзьях / не знаем
    since: datetime | None = None
    checked_at: datetime | None = None


class BaseFriendshipLookup(ABC):
    @abstractmethod
    async def get(
        self,
        buyer_id: int | None,
        steam_id: str | None,
    ) -> Friendship: ...


@dataclass(frozen=True)
class SnapshotFriendshipLookup(BaseFriendshipLookup):
    steam_repo: BaseSteamRepository

    async def get(
        self,
        buyer_id: int | None,
        steam_id: str | None,
    ) -> Friendship:
        friends, _, refreshed_at = await self.steam_repo.load_snapshot()
        for f in friends:
            if steam_id and f.steam_id == steam_id:
                return Friendship(
                    Relationship(f.relationship),
                    f.friend_since,
                    refreshed_at,
                )
        return Friendship(None, None, refreshed_at)


@dataclass(frozen=True)
class SandboxFriendshipLookup(BaseFriendshipLookup):
    sandbox: BaseSandboxRepository

    async def get(
        self,
        buyer_id: int | None,
        steam_id: str | None,
    ) -> Friendship:
        if buyer_id is None:
            return Friendship(None)
        stored = await self.sandbox.friendship(buyer_id)
        if stored is None:
            return Friendship(None)
        relationship, since = stored
        return Friendship(
            Relationship(relationship) if relationship else None,
            since,
        )
