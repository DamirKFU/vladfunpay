import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.core import messages
from app.integrations.provider import BaseIntegrations
from app.integrations.steam.base import SteamError
from app.models.app_settings import ProtectedFriend
from app.models.domain import Channel, FriendsReport, Relationship
from app.repositories.base import (
    BaseOrderRepository,
    BaseSteamLinkRepository,
    BaseSteamRepository,
)
from app.usecases.errors import ConflictError, ExternalServiceError
from app.usecases.friends_ranking import BuyerInfo, rank_friends
from app.usecases.settings import SettingsService

log = logging.getLogger('steam.friends')
LEVEL_CACHE_DAYS = 7
LEVEL_LOOKUPS_PER_REFRESH = 300
UNKNOWN_LEVEL = -1


@dataclass(frozen=True)
class FriendsService:
    settings: SettingsService
    steam_repo: BaseSteamRepository
    orders: BaseOrderRepository
    links: BaseSteamLinkRepository
    integrations: BaseIntegrations

    async def refresh(self) -> FriendsReport:
        """Забирает друзей из Steam, дополняет именами и уровнями."""
        settings = await self.settings.get()
        gateway = self.integrations.steam(settings)
        now = datetime.now(timezone.utc)
        try:
            friends = await gateway.friends()
            ids = [f.steam_id for f in friends]
            names = await gateway.summaries(ids)
            levels = await self.steam_repo.cached_levels(
                ids + [settings.steam.steam_id],
                now - timedelta(days=LEVEL_CACHE_DAYS),
            )
            missing = [
                i for i in [settings.steam.steam_id, *ids] if i not in levels
            ][:LEVEL_LOOKUPS_PER_REFRESH]
            fresh = await gateway.levels(missing)
        except SteamError as e:
            log.warning('Steam: обновление друзей не удалось: %s', e)
            raise ExternalServiceError(str(e)) from e
        # Скрытый уровень тоже кэшируем (как -1), чтобы не спрашивать
        # Steam о нём при каждом обновлении.
        fresh.update({i: UNKNOWN_LEVEL for i in missing if i not in fresh})
        await self.steam_repo.cache_levels(fresh, now)
        levels.update(fresh)
        levels = {k: v for k, v in levels.items() if v != UNKNOWN_LEVEL}
        enriched = [
            replace(
                f,
                name=f.name
                or (names[f.steam_id].name if f.steam_id in names else ''),
                avatar=names[f.steam_id].avatar if f.steam_id in names else '',
                level=levels.get(f.steam_id),
            )
            for f in friends
        ]
        await self.steam_repo.save_snapshot(
            enriched,
            levels.get(settings.steam.steam_id),
            now,
        )
        log.info('Steam: друзей и заявок %d', len(enriched))
        return await self.report()

    async def refresh_if_stale(self) -> bool:
        settings = await self.settings.get()
        hours = settings.friends.refresh_hours
        if hours <= 0 or not (
            settings.steam.api_key and settings.steam.steam_id
        ):
            return False
        _, _, refreshed_at = await self.steam_repo.load_snapshot()
        now = datetime.now(timezone.utc)
        if refreshed_at and now - refreshed_at < timedelta(hours=hours):
            return False
        await self.refresh()
        return True

    async def report(self) -> FriendsReport:
        settings = await self.settings.get()
        (
            friends,
            own_level,
            refreshed_at,
        ) = await self.steam_repo.load_snapshot()
        protected = {p.steam_id for p in settings.friends.protected}
        return rank_friends(
            friends,
            protected,
            await self._buyers(),
            datetime.now(timezone.utc),
            settings.friends.long_friend_days,
            own_level,
            settings.friends.keep_free_slots,
            refreshed_at,
        )

    async def _buyers(self) -> dict[str, BuyerInfo]:
        """Steam id -> покупатель: из выгрузки и из ссылок в чатах."""
        acc: dict[str, dict] = {}
        for order in await self.orders.list_all():
            if order.steam_id:
                self._add(
                    acc,
                    order.steam_id,
                    order.buyer_name,
                    order.paid_at,
                    order.status == 'paid',
                )
        for link in await self.links.list(Channel.FUNPAY):
            if link.steam_id:
                order = await self.orders.get(link.order_id)
                is_open = order is None or order.status == 'paid'
                self._add(
                    acc, link.steam_id, link.buyer_name, link.saved_at, is_open
                )
        return {
            sid: BuyerInfo(
                name=v['name'],
                orders=v['orders'],
                last_order_at=v['last'],
                has_open_order=v['open'],
            )
            for sid, v in acc.items()
        }

    @staticmethod
    def _add(
        acc: dict,
        steam_id: str,
        name: str,
        at: datetime | None,
        is_open: bool,
    ) -> None:
        item = acc.setdefault(
            steam_id,
            {'name': name, 'orders': 0, 'last': None, 'open': False},
        )
        item['orders'] += 1
        item['open'] = item['open'] or is_open
        if at and (item['last'] is None or at > item['last']):
            item['last'] = at
            item['name'] = name or item['name']

    async def remove(self, steam_ids: list[str]) -> list[dict]:
        """Удаляет выбранных. Защищённых и с открытым заказом — никогда."""
        settings = await self.settings.get()
        if not settings.friends.allow_removal:
            log.warning(
                'Удаление друзей отключено в настройках, отклонено: %d',
                len(steam_ids),
            )
            return [
                {'steam_id': sid, 'error': messages.STEAM_REMOVAL_DISABLED}
                for sid in steam_ids
            ]
        report = await self.report()
        by_id = {r.friend.steam_id: r for r in report.ranked}
        gateway = self.integrations.steam(settings)
        results = []
        for sid in steam_ids:
            item = by_id.get(sid)
            if item is None:
                results.append(
                    {
                        'steam_id': sid,
                        'error': messages.STEAM_NOT_FRIEND.format(sid),
                    },
                )
                continue
            if not item.removable:
                text = (
                    messages.STEAM_PROTECTED
                    if item.tier == 'protected'
                    else messages.STEAM_ACTIVE_ORDER
                )
                results.append({'steam_id': sid, 'error': text.format(sid)})
                continue
            try:
                await gateway.remove_friend(sid)
            except SteamError as e:
                results.append({'steam_id': sid, 'error': str(e)})
                continue
            await self.steam_repo.remove_from_snapshot(sid)
            log.info('Steam: удалён %s (%s)', sid, item.reason)
            results.append({'steam_id': sid, 'removed': True})
        return results

    async def protect(self, steam_id: str, note: str) -> None:
        settings = await self.settings.get()
        items = [
            p for p in settings.friends.protected if p.steam_id != steam_id
        ]
        items.append(ProtectedFriend(steam_id=steam_id, note=note))
        settings.friends.protected = items
        await self.settings.save(settings)

    async def unprotect(self, steam_id: str) -> None:
        settings = await self.settings.get()
        settings.friends.protected = [
            p for p in settings.friends.protected if p.steam_id != steam_id
        ]
        await self.settings.save(settings)

    async def auto_cleanup(self) -> list[dict]:
        """Автоочистка: только заявки и «просто друзья», если включена."""
        settings = await self.settings.get()
        if not (
            settings.friends.auto_cleanup and settings.friends.allow_removal
        ):
            return []
        report = await self.refresh()
        ids = [
            c.friend.steam_id
            for c in report.candidates
            if c.friend.relationship == Relationship.INVITE_SENT
            or c.tier == 'friend'
        ]
        if not ids:
            return []
        if len(ids) > 50:
            raise ConflictError('слишком много кандидатов, удалите вручную')
        return await self.remove(ids)
