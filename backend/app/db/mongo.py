from datetime import timezone

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.settings import Config

ORDERS = 'orders'
USERS = 'users'
SETTINGS = 'settings'
SYNC_RUNS = 'sync_runs'
LOGS = 'logs'
MESSAGES = 'chat_messages'
CONVERSATIONS = 'conversations'
TRACES = 'bot_traces'
USAGE = 'llm_usage'
STEAM_SNAPSHOT = 'steam_snapshot'
STEAM_LEVELS = 'steam_levels'
SANDBOX_OFFERS = 'sandbox_offers'
SANDBOX_ORDERS = 'sandbox_orders'
COUNTERS = 'counters'
STEAM_LINKS = 'steam_links'
SANDBOX_FRIENDS = 'sandbox_friends'
LOTS = 'lots'

# Коллекции в выгрузке базы. Пользователи и настройки отдаются отдельно,
# без хешей паролей и секретов.
EXPORT_COLLECTIONS = (
    ORDERS,
    SYNC_RUNS,
    MESSAGES,
    CONVERSATIONS,
    TRACES,
    USAGE,
    STEAM_SNAPSHOT,
    STEAM_LINKS,
    LOTS,
    SANDBOX_OFFERS,
    SANDBOX_ORDERS,
    LOGS,
)


def create_database(config: Config) -> AsyncDatabase:
    client: AsyncMongoClient = AsyncMongoClient(
        config.mongo_url,
        tz_aware=True,
        tzinfo=timezone.utc,
    )
    return client[config.mongo_db]


async def ensure_indexes(db: AsyncDatabase, log_ttl_days: int) -> None:
    await db[ORDERS].create_index('order_uid', unique=True)
    await db[ORDERS].create_index([('paid_at', ASCENDING)])
    await db[ORDERS].create_index([('buyer_id', ASCENDING)])
    await db[USERS].create_index('username', unique=True)
    await db[SYNC_RUNS].create_index([('started_at', DESCENDING)])
    await db[LOGS].create_index(
        'ts',
        expireAfterSeconds=log_ttl_days * 86400,
    )
    await db[LOGS].create_index([('level', ASCENDING), ('ts', DESCENDING)])
    await db[MESSAGES].create_index(
        [
            ('channel', ASCENDING),
            ('chat_id', ASCENDING),
            ('message_id', ASCENDING),
        ],
        unique=True,
    )
    await db[CONVERSATIONS].create_index(
        [('channel', ASCENDING), ('chat_id', ASCENDING)],
        unique=True,
    )
    await db[TRACES].create_index(
        [
            ('channel', ASCENDING),
            ('chat_id', ASCENDING),
            ('created_at', DESCENDING),
        ],
    )
    await db[USAGE].create_index('day', unique=True)
    await db[STEAM_LEVELS].create_index('steam_id', unique=True)
    await db[LOTS].create_index(
        [('channel', ASCENDING), ('lot_id', ASCENDING)],
        unique=True,
    )
    await db[STEAM_LINKS].create_index(
        [('channel', ASCENDING), ('order_id', ASCENDING)],
        unique=True,
    )
