from dataclasses import dataclass, field

from app.integrations.steam.base import (
    BaseSteamGateway,
    PlayerSummary,
)
from app.models.domain import SteamFriend


@dataclass
class MemorySteamGateway(BaseSteamGateway):
    """Steam в памяти: для тестов и проверки логики без аккаунта."""

    friend_list: list[SteamFriend] = field(default_factory=list)
    level_map: dict[str, int] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    vanity_map: dict[str, str] = field(default_factory=dict)
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

    async def resolve_vanity(self, vanity: str) -> str | None:
        return self.vanity_map.get(vanity)
