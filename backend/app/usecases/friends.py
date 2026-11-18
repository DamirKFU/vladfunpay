import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from app.core.timing import logged_call
from app.integrations.provider import BaseIntegrations
from app.integrations.steam.base import SteamError
from app.models.app_settings import ProtectedFriend
from app.models.domain import FriendsReport, Order
from app.repositories.base import (
    BaseOrderRepository,
    BaseSteamLinkRepository,
    BaseSteamRepository,
)
from app.usecases.errors import ExternalServiceError
from app.usecases.friends_ranking import BuyerInfo, rank_friends
from app.usecases.settings import SettingsService

log = logging.getLogger('steam.friends')
LEVEL_CACHE_DAYS = 7
UNKNOWN_LEVEL = -1


@dataclass(frozen=True)
class FriendsService:
    settings: SettingsService
    steam_repo: BaseSteamRepository
    orders: BaseOrderRepository
    links: BaseSteamLinkRepository
    integrations: BaseIntegrations

    async def refresh(self) -> FriendsReport:
        """Забирает друзей, заявки и уровень владельца для расчёта слотов."""
        async with logged_call(log, 'Steam: обновление списка друзей'):
            return await self._refresh()

    async def _refresh(self) -> FriendsReport:
        settings = await self.settings.get()
        gateway = self.integrations.steam(settings)
        now = datetime.now(timezone.utc)
        try:
            friends = await gateway.friends()
            ids = [f.steam_id for f in friends]
            names = await gateway.summaries(ids)
            own_id = settings.steam.steam_id
            levels = await self.steam_repo.cached_levels(
                [own_id],
                now - timedelta(days=LEVEL_CACHE_DAYS),
            )
            fresh = (
                await gateway.levels([own_id]) if own_id not in levels else {}
            )
        except SteamError as e:
            log.warning('Steam: обновление друзей не удалось: %s', e)
            raise ExternalServiceError(str(e)) from e
        # Скрытый уровень тоже кэшируем (как -1), чтобы не спрашивать
        # Steam о нём при каждом обновлении.
        if own_id not in levels:
            fresh.setdefault(own_id, UNKNOWN_LEVEL)
            await self.steam_repo.cache_levels(fresh, now)
        levels.update(fresh)
        levels = {k: v for k, v in levels.items() if v != UNKNOWN_LEVEL}
        enriched = [
            replace(
                f,
                name=f.name
                or (names[f.steam_id].name if f.steam_id in names else ''),
                avatar=names[f.steam_id].avatar if f.steam_id in names else '',
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
            own_level,
            refreshed_at,
        )

    async def _buyers(self) -> dict[str, BuyerInfo]:
        """Steam id -> покупатель: из выгрузки и ранее сохранённых привязок."""
        acc: dict[str, dict] = {}
        orders = {o.order_uid: o for o in await self.orders.list_all()}
        known = set()
        for order in orders.values():
            if order.steam_id:
                known.add((order.order_uid, order.steam_id))
                self._add(
                    acc,
                    order.steam_id,
                    order.buyer_name,
                    _purchase_at(order),
                    order.status == 'paid',
                )
        for link in await self.links.list('funpay'):
            pair = (link.order_id, link.steam_id)
            if not link.steam_id or pair in known:
                continue
            known.add(pair)
            order = orders.get(link.order_id)
            self._add(
                acc,
                link.steam_id,
                link.buyer_name,
                _purchase_at(order) if order else None,
                order is not None and order.status == 'paid',
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

    async def protect(self, steam_id: str, note: str) -> None:
        settings = await self.settings.get()
        items = [
            p for p in settings.friends.protected if p.steam_id != steam_id
        ]
        items.append(ProtectedFriend(steam_id=steam_id, note=note))
        settings.friends.protected = items
        await self.settings.save(settings)
        log.info(
            'Steam: защита %s включена', steam_id, extra={'steam_id': steam_id}
        )

    async def unprotect(self, steam_id: str) -> None:
        settings = await self.settings.get()
        settings.friends.protected = [
            p for p in settings.friends.protected if p.steam_id != steam_id
        ]
        await self.settings.save(settings)
        log.info(
            'Steam: защита %s снята', steam_id, extra={'steam_id': steam_id}
        )


def _purchase_at(order: Order) -> datetime | None:
    return order.paid_at if order.status != 'refunded' else None
