from dataclasses import dataclass, field

from app.core import messages
from app.integrations.steam.base import (
    BaseSteamGateway,
    PlayerSummary,
    SteamError,
)
from app.models.domain import SteamFriend


@dataclass
class MemorySteamGateway(BaseSteamGateway):
    """Steam в памяти: для тестов и проверки логики без аккаунта."""

    friend_list: list[SteamFriend] = field(default_factory=list)
    level_map: dict[str, int] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    vanity_map: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    level_calls: int = 0

    async def friends(self) -> list[SteamFriend]:
        return list(self.friend_list)

    async def levels(self, steam_ids: list[str]) -> dict[str, int]:
        self.level_calls += len(steam_ids)
        return {s: self.level_map[s] for s in steam_ids if s in self.level_map}

    async def summaries(
        self,
        steam_ids: list[str],
    ) -> dict[str, PlayerSummary]:
        return {
            s: PlayerSummary(name=self.names.get(s, s), avatar='')
            for s in steam_ids
        }

    async def remove_friend(self, steam_id: str) -> None:
        if not any(f.steam_id == steam_id for f in self.friend_list):
            raise SteamError(messages.STEAM_NOT_FRIEND.format(steam_id))
        self.friend_list = [
            f for f in self.friend_list if f.steam_id != steam_id
        ]
        self.removed.append(steam_id)

    async def resolve_vanity(self, vanity: str) -> str | None:
        return self.vanity_map.get(vanity)
