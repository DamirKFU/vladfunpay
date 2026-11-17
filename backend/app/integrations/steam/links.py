"""Разбор ссылок Steam, которые присылают покупатели."""

import re
from dataclasses import dataclass

STEAM_ID64_BASE = 76561197960265728

_PROFILE_RE = re.compile(
    r'https?://(?:www\.)?steamcommunity\.com/profiles/(\d{17})',
    re.I,
)
_VANITY_RE = re.compile(
    r'https?://(?:www\.)?steamcommunity\.com/id/([A-Za-z0-9_-]{2,64})',
    re.I,
)
_TRADE_RE = re.compile(
    r'https?://(?:www\.)?steamcommunity\.com/tradeoffer/new/\?'
    r'[^\s]*?partner=(\d+)(?:[^\s]*?&token=([A-Za-z0-9_-]+))?',
    re.I,
)
_ANY_STEAM_RE = re.compile(
    r'https?://(?:www\.)?steamcommunity\.com/[^\s<>"\']+',
    re.I,
)


@dataclass(frozen=True)
class SteamLink:
    url: str
    steam_id: str | None = None
    vanity: str | None = None
    trade_token: str | None = None


def account_id_to_steam_id(account_id: int) -> str:
    return str(STEAM_ID64_BASE + account_id)


def parse_steam_link(text: str) -> SteamLink | None:
    """Первая ссылка Steam в тексте: профиль, /id/ или трейд-ссылка."""
    if m := _TRADE_RE.search(text):
        return SteamLink(
            url=m.group(0),
            steam_id=account_id_to_steam_id(int(m.group(1))),
            trade_token=m.group(2),
        )
    if m := _PROFILE_RE.search(text):
        return SteamLink(url=m.group(0), steam_id=m.group(1))
    if m := _VANITY_RE.search(text):
        return SteamLink(url=m.group(0), vanity=m.group(1))
    if m := _ANY_STEAM_RE.search(text):
        return SteamLink(url=m.group(0))
    return None
