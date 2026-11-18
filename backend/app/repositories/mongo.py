import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any, TypeVar

from pymongo import DESCENDING, UpdateOne
from pymongo.asynchronous.database import AsyncDatabase

from app.db import mongo as names
from app.models.domain import (
    LogEntry,
    Order,
    SalePreview,
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

T = TypeVar('T')
SETTINGS_ID = 'app'


def _build(cls: type[T], doc: dict[str, Any]) -> T:
    allowed = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    return cls(**{k: v for k, v in doc.items() if k in allowed})


@dataclass(frozen=True)
class MongoUserRepository(BaseUserRepository):
    db: AsyncDatabase

    async def count(self) -> int:
        return await self.db[names.USERS].count_documents({})

    async def get(self, username: str) -> User | None:
        doc = await self.db[names.USERS].find_one({'username': username})
        return _build(User, doc) if doc else None

    async def list(self) -> list[User]:
        cursor = self.db[names.USERS].find().sort('created_at')
        return [_build(User, d) async for d in cursor]

    async def save(self, user: User) -> None:
        await self.db[names.USERS].replace_one(
            {'username': user.username},
            asdict(user),
            upsert=True,
        )

    async def delete(self, username: str) -> None:
        await self.db[names.USERS].delete_one({'username': username})


@dataclass(frozen=True)
class MongoSettingsRepository(BaseSettingsRepository):
    db: AsyncDatabase

    async def load(self) -> dict[str, Any]:
        doc = await self.db[names.SETTINGS].find_one({'_id': SETTINGS_ID})
        return (doc or {}).get('data', {})

    async def save(self, data: dict[str, Any]) -> None:
        await self.db[names.SETTINGS].replace_one(
            {'_id': SETTINGS_ID},
            {'_id': SETTINGS_ID, 'data': data},
            upsert=True,
        )


@dataclass(frozen=True)
class MongoOrderRepository(BaseOrderRepository):
    db: AsyncDatabase

    async def upsert_many(self, orders: list[Order]) -> int:
        if not orders:
            return 0
        ops = []
        for order in orders:
            doc = asdict(order)
            # Steam-ссылку, сохранённую ботом, выгрузка не затирает.
            if not order.steam_id:
                doc.pop('steam_id')
                doc.pop('steam_link')
            ops.append(
                UpdateOne(
                    {'order_uid': order.order_uid},
                    {'$set': doc},
                    upsert=True,
                ),
            )
        await self.db[names.ORDERS].bulk_write(ops, ordered=False)
        return len(ops)

    async def get(self, order_uid: str) -> Order | None:
        doc = await self.db[names.ORDERS].find_one({'order_uid': order_uid})
        return _build(Order, doc) if doc else None

    async def list_all(self) -> list[Order]:
        cursor = self.db[names.ORDERS].find().sort('paid_at')
        return [_build(Order, d) async for d in cursor]

    async def count(self) -> int:
        return await self.db[names.ORDERS].count_documents({})

    async def max_paid_at(self) -> datetime | None:
        doc = await self.db[names.ORDERS].find_one(
            {'paid_at': {'$ne': None}},
            sort=[('paid_at', DESCENDING)],
        )
        return doc['paid_at'] if doc else None

    async def min_paid_at(self, status: str) -> datetime | None:
        doc = await self.db[names.ORDERS].find_one(
            {'status': status, 'paid_at': {'$ne': None}},
            sort=[('paid_at', 1)],
        )
        return doc['paid_at'] if doc else None

    async def by_buyer(self, buyer_id: int) -> list[Order]:
        cursor = self.db[names.ORDERS].find({'buyer_id': buyer_id})
        return [_build(Order, d) async for d in cursor]

    async def set_steam(
        self,
        order_uid: str,
        link: str,
        steam_id: str | None,
    ) -> None:
        await self.db[names.ORDERS].update_one(
            {'order_uid': order_uid},
            {'$set': {'steam_link': link, 'steam_id': steam_id}},
        )

    async def node_ids(self) -> list[int]:
        values = await self.db[names.ORDERS].distinct('node_id')
        return sorted(v for v in values if v)

    async def game_ids(self) -> list[int]:
        values = await self.db[names.ORDERS].distinct('raw.game.game_id')
        return sorted(v for v in values if v)


@dataclass(frozen=True)
class MongoSyncRunRepository(BaseSyncRunRepository):
    db: AsyncDatabase

    async def save(self, run: SyncRun) -> None:
        await self.db[names.SYNC_RUNS].replace_one(
            {'id': run.id},
            asdict(run),
            upsert=True,
        )

    async def latest(self, limit: int) -> list[SyncRun]:
        cursor = (
            self.db[names.SYNC_RUNS]
            .find()
            .sort('started_at', DESCENDING)
            .limit(limit)
        )
        return [_build(SyncRun, d) async for d in cursor]


@dataclass(frozen=True)
class MongoLogRepository(BaseLogRepository):
    db: AsyncDatabase

    async def insert_many(self, entries: list[LogEntry]) -> None:
        if entries:
            await self.db[names.LOGS].insert_many(
                [asdict(e) for e in entries],
            )

    async def query(
        self,
        level: str | None,
        source: str | None,
        search: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[LogEntry]:
        flt: dict[str, Any] = {}
        if level:
            flt['level'] = level
        if source:
            flt['source'] = source
        if search:
            flt['message'] = {'$regex': _escape(search), '$options': 'i'}
        if since:
            flt['ts'] = {'$gte': since}
        cursor = (
            self.db[names.LOGS].find(flt).sort('ts', DESCENDING).limit(limit)
        )
        return [_build(LogEntry, d) async for d in cursor]

    async def sources(self) -> list[str]:
        return sorted(await self.db[names.LOGS].distinct('source'))


def _escape(text: str) -> str:
    return re.escape(text)


@dataclass(frozen=True)
class MongoSteamRepository(BaseSteamRepository):
    db: AsyncDatabase

    async def save_snapshot(
        self,
        friends: list[SteamFriend],
        own_level: int | None,
        refreshed_at: datetime,
    ) -> None:
        await self.db[names.STEAM_SNAPSHOT].replace_one(
            {'_id': 'snapshot'},
            {
                '_id': 'snapshot',
                'friends': [asdict(f) for f in friends],
                'own_level': own_level,
                'refreshed_at': refreshed_at,
            },
            upsert=True,
        )

    async def load_snapshot(
        self,
    ) -> tuple[list[SteamFriend], int | None, datetime | None]:
        doc = await self.db[names.STEAM_SNAPSHOT].find_one(
            {'_id': 'snapshot'},
        )
        if not doc:
            return [], None, None
        friends = [_build(SteamFriend, f) for f in doc.get('friends', [])]
        return friends, doc.get('own_level'), doc.get('refreshed_at')

    async def cached_levels(
        self,
        steam_ids: list[str],
        newer_than: datetime,
    ) -> dict[str, int]:
        cursor = self.db[names.STEAM_LEVELS].find(
            {'steam_id': {'$in': steam_ids}, 'at': {'$gte': newer_than}},
        )
        return {d['steam_id']: d['level'] async for d in cursor}

    async def cache_levels(
        self,
        levels: dict[str, int],
        at: datetime,
    ) -> None:
        ops = [
            UpdateOne(
                {'steam_id': sid},
                {'$set': {'steam_id': sid, 'level': lvl, 'at': at}},
                upsert=True,
            )
            for sid, lvl in levels.items()
        ]
        if ops:
            await self.db[names.STEAM_LEVELS].bulk_write(ops)


@dataclass(frozen=True)
class MongoSteamLinkRepository(BaseSteamLinkRepository):
    db: AsyncDatabase

    async def list(self, channel: str) -> list[SteamLinkRecord]:
        cursor = self.db[names.STEAM_LINKS].find({'channel': str(channel)})
        return [_build(SteamLinkRecord, d) async for d in cursor]


@dataclass(frozen=True)
class MongoSalesSnapshotRepository(BaseSalesSnapshotRepository):
    db: AsyncDatabase

    async def load(self) -> SalesSnapshot | None:
        doc = await self.db[names.SALES_SNAPSHOT].find_one({'_id': 'latest'})
        if doc is None:
            return None
        return SalesSnapshot(
            refreshed_at=doc['refreshed_at'],
            items=[_build(SalePreview, item) for item in doc['items']],
        )

    async def save(self, snapshot: SalesSnapshot) -> None:
        await self.db[names.SALES_SNAPSHOT].replace_one(
            {'_id': 'latest'},
            asdict(snapshot),
            upsert=True,
        )
