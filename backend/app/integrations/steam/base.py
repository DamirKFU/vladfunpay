from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.domain import SteamFriend


class SteamError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlayerSummary:
    name: str
    avatar: str


class BaseSteamGateway(ABC):
    @abstractmethod
    async def friends(self) -> list[SteamFriend]:
        """Друзья и ожидающие заявки (входящие и исходящие)."""

    @abstractmethod
    async def levels(self, steam_ids: list[str]) -> dict[str, int]: ...

    @abstractmethod
    async def summaries(
        self,
        steam_ids: list[str],
    ) -> dict[str, PlayerSummary]: ...

    @abstractmethod
    async def remove_friend(self, steam_id: str) -> None:
        """Удаляет друга или отменяет заявку."""

    @abstractmethod
    async def resolve_vanity(self, vanity: str) -> str | None: ...


def friend_limit(level: int | None) -> int | None:
    """Лимит друзей Steam: 250 + 5 за уровень, не больше 2000."""
    if level is None:
        return None
    return min(2000, 250 + 5 * level)
