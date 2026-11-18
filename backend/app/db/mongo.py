from datetime import timezone

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.settings import Config

ORDERS = 'orders'
USERS = 'users'
SETTINGS = 'settings'
SYNC_RUNS = 'sync_runs'
LOGS = 'logs'
STEAM_SNAPSHOT = 'steam_snapshot'
STEAM_LEVELS = 'steam_levels'
STEAM_LINKS = 'steam_links'
SALES_SNAPSHOT = 'sales_snapshot'

# Коллекции в выгрузке базы. Пользователи и настройки отдаются отдельно,
# без хешей паролей и секретов.
EXPORT_COLLECTIONS = (
    ORDERS,
    SYNC_RUNS,
    STEAM_SNAPSHOT,
    SALES_SNAPSHOT,
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
    await db[STEAM_LEVELS].create_index('steam_id', unique=True)
