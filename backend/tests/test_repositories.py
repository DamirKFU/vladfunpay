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
    Author,
    BotTrace,
    Channel,
    ChatMessage,
    Conversation,
    LogEntry,
    Offer,
    OpenOrder,
    Relationship,
    SteamFriend,
    ToolCallTrace,
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
            'chats': memory.MemoryChatRepository(),
            'logs': memory.MemoryLogRepository(),
            'usage': memory.MemoryUsageRepository(),
            'steam': memory.MemorySteamRepository(),
            'sandbox': memory.MemorySandboxRepository(),
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
        'chats': mongo.MongoChatRepository(db),
        'logs': mongo.MongoLogRepository(db),
        'usage': mongo.MongoUsageRepository(db),
        'steam': mongo.MongoSteamRepository(db),
        'sandbox': mongo.MongoSandboxRepository(db),
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


async def test_chats_messages_conversations_traces(repos):
    chats = repos['chats']
    for i in (2, 1, 2):  # повтор id не дублирует
        await chats.add_message(
            ChatMessage(Channel.SANDBOX, 'c1', i, Author.BUYER, f'm{i}', NOW),
        )
    msgs = await chats.messages(Channel.SANDBOX, 'c1', 10)
    assert [m.message_id for m in msgs] == [1, 2]

    conv = Conversation(Channel.SANDBOX, 'c1', 5, 'b', NOW)
    await chats.save_conversation(conv)
    conv.needs_human = True
    await chats.save_conversation(conv)
    loaded = await chats.get_conversation(Channel.SANDBOX, 'c1')
    assert loaded.needs_human is True
    assert len(await chats.conversations(Channel.SANDBOX, 10)) == 1
    assert await chats.conversations(Channel.FUNPAY, 10) == []

    await chats.add_trace(
        BotTrace(
            Channel.SANDBOX,
            'c1',
            NOW,
            'hi',
            'yo',
            'replied',
            tool_calls=[ToolCallTrace('get_open_orders', {}, [])],
        ),
    )
    traces = await chats.traces(Channel.SANDBOX, 'c1', 5)
    assert traces[0].tool_calls[0].name == 'get_open_orders'

    await chats.clear(Channel.SANDBOX, 'c1')
    assert await chats.messages(Channel.SANDBOX, 'c1', 10) == []


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


async def test_usage_and_steam_and_sandbox(repos):
    usage = repos['usage']
    assert await usage.add_tokens('2026-11-17', 10) == 10
    assert await usage.add_tokens('2026-11-17', 5) == 15
    assert await usage.tokens('2026-11-18') == 0

    steam = repos['steam']
    friend = SteamFriend('1', Relationship.FRIEND, 'n', 3, NOW)
    await steam.save_snapshot([friend], 10, NOW)
    friends, level, at = await steam.load_snapshot()
    assert friends[0].name == 'n' and level == 10 and at == NOW
    await steam.remove_from_snapshot('1')
    assert (await steam.load_snapshot())[0] == []
    await steam.cache_levels({'1': 5}, NOW)
    assert await steam.cached_levels(['1', '2'], NOW - timedelta(days=1)) == {
        '1': 5,
    }
    assert await steam.cached_levels(['1'], NOW + timedelta(days=1)) == {}

    sandbox = repos['sandbox']
    assert await sandbox.next_id('x') == 1
    assert await sandbox.next_id('x') == 2
    await sandbox.save_offer(Offer('lot1', 'Item', 10.0, 3))
    assert (await sandbox.offers())[0].amount == 3
    await sandbox.save_order(OpenOrder('T1', 'Item', 10.0, 7, 'b'))
    assert len(await sandbox.orders(7)) == 1
    assert await sandbox.orders(8) == []


async def test_sandbox_friendship(repos):
    sandbox = repos['sandbox']
    assert await sandbox.friendship(5) is None
    await sandbox.set_friendship(5, 'friend', NOW)
    assert await sandbox.friendship(5) == ('friend', NOW)
    await sandbox.set_friendship(5, None, None)
    assert await sandbox.friendship(5) == (None, None)
