"""Контрактные тесты репозиториев: одни и те же проверки для памяти и Mongo.

Mongo-вариант запускается, если задан MONGO_TEST_URL, например:
    docker compose run --rm backend-tests
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.funpay.orders import order_from_export
from app.models.domain import (
    LogEntry,
    Relationship,
    SalePreview,
    SalesSnapshot,
    SteamFriend,
)
from app.repositories import memory, mongo

MONGO_URL = os.environ.get('MONGO_TEST_URL')
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

KINDS = ['memory'] + (['mongo'] if MONGO_URL else [])


@pytest.fixture(params=KINDS)
async def repos(request):
    if request.param == 'memory':
        yield {
            'orders': memory.MemoryOrderRepository(),
            'logs': memory.MemoryLogRepository(),
            'steam': memory.MemorySteamRepository(),
            'sales': memory.MemorySalesSnapshotRepository(),
        }
        return
    from pymongo import AsyncMongoClient

    from app.db.mongo import ensure_indexes

    client = AsyncMongoClient(MONGO_URL, tz_aware=True, tzinfo=timezone.utc)
    name = f'test_{uuid.uuid4().hex[:8]}'
    db = client[name]
    await ensure_indexes(db, 30)
    yield {
        'orders': mongo.MongoOrderRepository(db),
        'logs': mongo.MongoLogRepository(db),
        'steam': mongo.MongoSteamRepository(db),
        'sales': mongo.MongoSalesSnapshotRepository(db),
    }
    await client.drop_database(name)
    await client.close()


async def test_orders_upsert_keeps_bot_steam_link(repos, export_records):
    orders = repos['orders']
    first = [order_from_export(r) for r in export_records]
    await orders.upsert_many(first)
    await orders.set_steam('EFGH5678', 'https://link', '765')

    again = order_from_export(export_records[1])
    again.steam_id = again.steam_link = None
    again.status = 'closed'
    await orders.upsert_many([again])

    stored = await orders.get('EFGH5678')
    assert stored.status == 'closed'
    assert stored.steam_id == '765'
    assert await orders.count() == 3
    assert (await orders.max_paid_at()).year == 2025
    assert (await orders.min_paid_at('paid')).month == 11
    assert [o.order_uid for o in await orders.by_buyer(1003)] == ['OPEN0001']
    assert await orders.node_ids() == [210]


async def test_logs_query(repos):
    logs = repos['logs']
    await logs.insert_many(
        [
            LogEntry(NOW - timedelta(hours=2), 'INFO', 'bot', 'старое'),
            LogEntry(NOW, 'ERROR', 'sync', 'Ошибка (выгрузки)'),
        ]
    )
    assert [
        e.message for e in await logs.query(None, None, None, None, 10)
    ] == ['Ошибка (выгрузки)', 'старое']
    assert len(await logs.query('ERROR', None, None, None, 10)) == 1
    found = await logs.query(None, None, '(выгрузки', None, 10)
    assert len(found) == 1
    assert (
        len(await logs.query(None, None, None, NOW - timedelta(hours=1), 10))
        == 1
    )
    assert await logs.sources() == ['bot', 'sync']


async def test_steam_snapshot_and_cache(repos):
    steam = repos['steam']
    friend = SteamFriend('1', Relationship.FRIEND, 'n', NOW)
    await steam.save_snapshot([friend], 10, NOW)
    friends, level, at = await steam.load_snapshot()
    assert friends[0].name == 'n' and level == 10 and at == NOW
    await steam.cache_levels({'1': 5}, NOW)
    assert await steam.cached_levels(['1', '2'], NOW - timedelta(days=1)) == {
        '1': 5,
    }
    assert await steam.cached_levels(['1'], NOW + timedelta(days=1)) == {}


async def test_sales_snapshot_replaced_atomically(repos):
    sales = repos['sales']
    assert await sales.load() is None
    order = SalePreview('SALE', 'Item', 'buyer', 10, '₽', 'paid', 'сегодня')
    await sales.save(SalesSnapshot(NOW, [order]))
    assert await sales.load() == SalesSnapshot(NOW, [order])
    later = NOW + timedelta(minutes=2)
    await sales.save(SalesSnapshot(later, []))
    assert await sales.load() == SalesSnapshot(later, [])
