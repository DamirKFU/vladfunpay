from functools import lru_cache

from punq import Container, Scope
from pymongo.asynchronous.database import AsyncDatabase

from app.bot.service import BotService
from app.core.security import SecretBox, load_or_create_key
from app.db.dump import MongoDatabaseDumper
from app.db.mongo import create_database
from app.integrations.funpay.sandbox import SandboxMarketplace
from app.integrations.provider import BaseIntegrations, LiveIntegrations
from app.integrations.steam.friendship import (
    SandboxFriendshipLookup,
    SnapshotFriendshipLookup,
)
from app.repositories import base, mongo
from app.settings import Config
from app.usecases.alerts import OwnerAlerts
from app.usecases.auth import AuthService, LoginLimiter
from app.usecases.chats import ChatService, SandboxService
from app.usecases.data import (
    BaseDatabaseDumper,
    DatabaseExportService,
    LogService,
    ReportService,
)
from app.usecases.friends import FriendsService
from app.usecases.lots import LotCatalogService
from app.usecases.raise_lots import RaiseService
from app.usecases.settings import SettingsService
from app.usecases.sync import SyncService
from app.workers.runtime import FunPayMarketplaceProvider, Workers

REPOSITORIES = (
    (base.BaseUserRepository, mongo.MongoUserRepository),
    (base.BaseSettingsRepository, mongo.MongoSettingsRepository),
    (base.BaseOrderRepository, mongo.MongoOrderRepository),
    (base.BaseSyncRunRepository, mongo.MongoSyncRunRepository),
    (base.BaseLogRepository, mongo.MongoLogRepository),
    (base.BaseChatRepository, mongo.MongoChatRepository),
    (base.BaseUsageRepository, mongo.MongoUsageRepository),
    (base.BaseSteamRepository, mongo.MongoSteamRepository),
    (base.BaseSteamLinkRepository, mongo.MongoSteamLinkRepository),
    (base.BaseSandboxRepository, mongo.MongoSandboxRepository),
    (base.BaseLotRepository, mongo.MongoLotRepository),
)

SINGLETONS = (
    SettingsService,
    AuthService,
    LoginLimiter,
    SyncService,
    FriendsService,
    ReportService,
    LogService,
    DatabaseExportService,
    ChatService,
    SandboxMarketplace,
    SandboxService,
    SnapshotFriendshipLookup,
    SandboxFriendshipLookup,
    OwnerAlerts,
    RaiseService,
    LotCatalogService,
    BotService,
    FunPayMarketplaceProvider,
    Workers,
)


@lru_cache(1)
def init_container() -> Container:
    return _init_container()


def _init_container() -> Container:
    container = Container()
    config = Config()
    container.register(Config, instance=config, scope=Scope.singleton)

    def init_box() -> SecretBox:
        return SecretBox(load_or_create_key(config.secret_key_path))

    def init_db() -> AsyncDatabase:
        return create_database(config)

    container.register(SecretBox, factory=init_box, scope=Scope.singleton)
    container.register(AsyncDatabase, factory=init_db, scope=Scope.singleton)
    for service, impl in REPOSITORIES:
        container.register(service, impl, scope=Scope.singleton)
    container.register(
        BaseIntegrations,
        LiveIntegrations,
        scope=Scope.singleton,
    )
    container.register(
        BaseDatabaseDumper,
        MongoDatabaseDumper,
        scope=Scope.singleton,
    )
    for cls in SINGLETONS:
        container.register(cls, scope=Scope.singleton)
    return container
