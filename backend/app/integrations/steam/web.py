"""Steam: официальный Web API (ключ) + cookie steamcommunity.com.

Web API (лимит 100 000 вызовов в сутки): список друзей с датой
дружбы, имена, уровни. Ожидающие заявки и удаление делаются через сайт
steamcommunity.com с cookie steamLoginSecure и sessionid — это серая
зона, поэтому в интерфейсе удаление всегда подтверждается вручную.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

from app.core import messages
from app.integrations.steam.base import (
    BaseSteamGateway,
    PlayerSummary,
    SteamError,
)
from app.models.domain import Relationship, SteamFriend

log = logging.getLogger('steam')

API = 'https://api.steampowered.com'
COMMUNITY = 'https://steamcommunity.com'
SUMMARIES_BATCH = 100
PAUSE_SEC = 0.1
LEVEL_CONCURRENCY = 8


@dataclass
class SteamWebGateway(BaseSteamGateway):
    api_key: str
    steam_id: str
    login_secure: str = ''
    session_id: str = ''
    user_agent: str = 'Mozilla/5.0'

    def _client(self) -> httpx.AsyncClient:
        cookies = {}
        if self.login_secure:
            cookies['steamLoginSecure'] = self.login_secure
        if self.session_id:
            cookies['sessionid'] = self.session_id
        return httpx.AsyncClient(
            timeout=30,
            cookies=cookies,
            headers={'User-Agent': self.user_agent},
            follow_redirects=True,
        )

    async def _api(
        self,
        path: str,
        use_token: bool = False,
        **params: str,
    ) -> dict:
        auth = (
            {'access_token': access_token(self.login_secure)}
            if use_token
            else {'key': self.api_key}
        )
        start = perf_counter()
        try:
            async with self._client() as client:
                resp = await client.get(
                    f'{API}/{path}',
                    params={**auth, 'format': 'json', **params},
                )
        except httpx.HTTPError as e:
            log.warning('Steam API %s: сеть: %s', path, e)
            raise SteamError(messages.STEAM_REQUEST_FAILED.format(e)) from e
        ms = (perf_counter() - start) * 1000
        via = 'token' if use_token else 'key'
        if resp.status_code != 200:
            log.warning(
                'Steam API %s (%s) → HTTP %d за %.0f мс: %s',
                path,
                via,
                resp.status_code,
                ms,
                resp.text[:300],
            )
            raise SteamError(explain_status(path, resp.status_code))
        log.info('Steam API %s (%s) → 200 за %.0f мс', path, via, ms)
        return resp.json()

    async def friends(self) -> list[SteamFriend]:
        params = {'steamid': self.steam_id, 'relationship': 'friend'}
        try:
            data = await self._api('ISteamUser/GetFriendList/v1', **params)
        except SteamError:
            if not access_token(self.login_secure):
                raise
            # Скрытый список друзей с ключом даёт 401. Пробуем токеном из
            # cookie steamLoginSecure (так делает сам сайт Steam) — НЕ
            # проверено на живом аккаунте, результат видно в логах.
            log.warning(
                'Steam: список друзей по ключу недоступен, пробую токен '
                'из cookie steamLoginSecure',
            )
            data = await self._api(
                'ISteamUser/GetFriendList/v1',
                use_token=True,
                **params,
            )
        result = [
            SteamFriend(
                steam_id=f['steamid'],
                relationship=Relationship.FRIEND,
                friend_since=datetime.fromtimestamp(
                    f.get('friend_since', 0),
                    tz=timezone.utc,
                ),
            )
            for f in data.get('friendslist', {}).get('friends', [])
        ]
        if self.login_secure:
            result.extend(await self._pending())
        return result

    async def _pending(self) -> list[SteamFriend]:
        url = f'{COMMUNITY}/profiles/{self.steam_id}/friends/pending'
        async with self._client() as client:
            resp = await client.get(url)
        if resp.status_code != 200 or '/login' in str(resp.url):
            log.warning(
                'Steam: страница заявок недоступна (HTTP %d, %s) — '
                'обновите cookie steamLoginSecure',
                resp.status_code,
                resp.url,
            )
            return []
        pending = parse_pending_page(resp.text)
        log.info('Steam: заявок в друзья на странице: %d', len(pending))
        return pending

    async def levels(self, steam_ids: list[str]) -> dict[str, int]:
        """Уровни параллельно (LEVEL_CONCURRENCY запросов сразу).

        По одному 150 друзей грузились 2 минуты. Ошибка по одному профилю
        не ломает всё обновление: уровень просто останется неизвестным.
        """
        result: dict[str, int] = {}
        limit = asyncio.Semaphore(LEVEL_CONCURRENCY)

        async def one(sid: str) -> None:
            async with limit:
                try:
                    data = await self._api(
                        'IPlayerService/GetSteamLevel/v1',
                        steamid=sid,
                    )
                except SteamError as e:
                    log.warning('Steam: уровень %s не получен: %s', sid, e)
                    return
                level = data.get('response', {}).get('player_level')
                if level is not None:
                    result[sid] = int(level)
                await asyncio.sleep(PAUSE_SEC)

        start = perf_counter()
        await asyncio.gather(*(one(sid) for sid in steam_ids))
        if steam_ids:
            log.info(
                'Steam: уровни %d профилей за %.1f с',
                len(steam_ids),
                perf_counter() - start,
            )
        return result

    async def summaries(
        self,
        steam_ids: list[str],
    ) -> dict[str, PlayerSummary]:
        result = {}
        for i in range(0, len(steam_ids), SUMMARIES_BATCH):
            chunk = steam_ids[i : i + SUMMARIES_BATCH]
            data = await self._api(
                'ISteamUser/GetPlayerSummaries/v2',
                steamids=','.join(chunk),
            )
            for p in data.get('response', {}).get('players', []):
                result[p['steamid']] = PlayerSummary(
                    name=p.get('personaname', ''),
                    avatar=p.get('avatarmedium', ''),
                )
        return result

    async def remove_friend(self, steam_id: str) -> None:
        if not (self.login_secure and self.session_id):
            raise SteamError(
                messages.SETTINGS_NOT_CONFIGURED.format(
                    'Steam steamLoginSecure и sessionid',
                ),
            )
        async with self._client() as client:
            resp = await client.post(
                f'{COMMUNITY}/actions/RemoveFriendAjax',
                data={'sessionID': self.session_id, 'steamid': steam_id},
            )
        if resp.status_code != 200 or resp.text.strip() in ('false', ''):
            log.warning(
                'Steam: удаление %s не удалось: HTTP %d %s',
                steam_id,
                resp.status_code,
                resp.text[:200],
            )
            raise SteamError(
                messages.STEAM_REQUEST_FAILED.format(
                    f'удаление {steam_id}: HTTP {resp.status_code}',
                ),
            )
        log.info('Steam: удалён %s', steam_id, extra={'steam_id': steam_id})

    async def resolve_vanity(self, vanity: str) -> str | None:
        data = await self._api(
            'ISteamUser/ResolveVanityURL/v1',
            vanityurl=vanity,
        )
        response = data.get('response', {})
        return (
            response.get('steamid') if response.get('success') == 1 else None
        )


def access_token(login_secure: str) -> str:
    """JWT из cookie steamLoginSecure («<steamid>||<token>»)."""
    value = unquote(login_secure or '')
    return value.split('||', 1)[1] if '||' in value else ''


def explain_status(path: str, status: int) -> str:
    if status == 401 and 'GetFriendList' in path:
        detail = (
            'HTTP 401 — список друзей скрыт. Steam → Профиль → '
            'Редактировать → Приватность → «Список друзей»: «Открытый». '
            'Или неверный ключ Web API'
        )
    elif status in (401, 403):
        detail = f'{path}: HTTP {status} — проверьте ключ Steam Web API'
    elif status == 429:
        detail = f'{path}: HTTP 429 — слишком много запросов, подождите'
    else:
        detail = f'{path}: HTTP {status}'
    return messages.STEAM_REQUEST_FAILED.format(detail)


def parse_pending_page(html: str) -> list[SteamFriend]:
    """Заявки со страницы /friends/pending.

    Блоки с data-steamid внутри контейнера с id/классом, где есть
    «sent», считаем исходящими, остальные — входящими. Разметку Steam
    меняет, поэтому разбор best effort: при сбое заявки просто не видны.
    """
    soup = BeautifulSoup(html, 'html.parser')
    result: dict[str, SteamFriend] = {}
    for node in soup.select('[data-steamid]'):
        sid = str(node.get('data-steamid'))
        if not sid.isdigit() or len(sid) != 17:
            continue
        sent = False
        for parent in node.parents:
            marker = ' '.join(
                [str(parent.get('id') or '')]
                + list(parent.get('class') or []),
            ).lower()
            if 'sent' in marker:
                sent = True
                break
        name_node = node.select_one('.invite_block_name a, .persona_name')
        result[sid] = SteamFriend(
            steam_id=sid,
            relationship=(
                Relationship.INVITE_SENT
                if sent
                else Relationship.INVITE_RECEIVED
            ),
            name=name_node.get_text(strip=True) if name_node else '',
        )
    return list(result.values())
