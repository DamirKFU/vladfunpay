import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

os.environ['RUN_WORKERS'] = '0'

from fastapi.testclient import TestClient  # noqa: E402
from punq import Container, Scope  # noqa: E402

from app.application.main import create_app  # noqa: E402
from app.core.security import SecretBox  # noqa: E402
from app.integrations.funpay.base import (  # noqa: E402
    BaseOrderExporter,
    SalesReader,
)
from app.integrations.funpay.memory import (  # noqa: E402
    MemoryLotRaiser,
    MemoryOrderExporter,
)
from app.integrations.provider import BaseIntegrations  # noqa: E402
from app.integrations.steam.base import BaseSteamGateway  # noqa: E402
from app.integrations.steam.memory import MemorySteamGateway  # noqa: E402
from app.models.app_settings import AppSettings  # noqa: E402
from app.models.domain import SalePreview  # noqa: E402
from app.repositories import base, memory  # noqa: E402
from app.settings import Config  # noqa: E402
from app.usecases.data import BaseDatabaseDumper  # noqa: E402
from app.usecases.settings import SettingsService  # noqa: E402

pytest_plugins = ['fixtures.records']


@dataclass
class MemorySalesReader(SalesReader):
    items: list[SalePreview] = field(default_factory=list)
    fail: bool = False

    async def sales(self) -> list[SalePreview]:
        if self.fail:
            raise RuntimeError('FunPay unavailable')
        return list(self.items)


@dataclass
class MemoryIntegrations(BaseIntegrations):
    """Внешние сервисы в памяти. Сами реализации — не моки, а рабочие
    классы с тем же интерфейсом."""

    order_exporter: MemoryOrderExporter = field(
        default_factory=MemoryOrderExporter,
    )
    steam_gateway: MemorySteamGateway = field(
        default_factory=MemorySteamGateway,
    )
    lot_raiser: MemoryLotRaiser = field(default_factory=MemoryLotRaiser)

    sales_reader: MemorySalesReader = field(default_factory=MemorySalesReader)

    def sales(self, s: AppSettings) -> SalesReader:
        return self.sales_reader

    def exporter(self, s: AppSettings) -> BaseOrderExporter:
        return self.order_exporter

    def steam(self, s: AppSettings) -> BaseSteamGateway:
        return self.steam_gateway

    def raiser(self, s: AppSettings):
        return self.lot_raiser


class NoDumper(BaseDatabaseDumper):
    async def dump(self, archive):
        archive.writestr('orders.jsonl', b'')
        return ['orders']


MEMORY_REPOSITORIES = (
    (base.BaseUserRepository, memory.MemoryUserRepository),
    (base.BaseSettingsRepository, memory.MemorySettingsRepository),
    (base.BaseOrderRepository, memory.MemoryOrderRepository),
    (base.BaseSyncRunRepository, memory.MemorySyncRunRepository),
    (base.BaseLogRepository, memory.MemoryLogRepository),
    (base.BaseSalesSnapshotRepository, memory.MemorySalesSnapshotRepository),
    (base.BaseSteamRepository, memory.MemorySteamRepository),
    (base.BaseSteamLinkRepository, memory.MemorySteamLinkRepository),
)


def init_dummy_container(tmp_path: Path) -> Container:
    from app.container import _init_container

    container = _init_container()
    container.register(
        Config,
        instance=Config(data_dir=tmp_path, run_workers=False),
        scope=Scope.singleton,
    )
    container.register(
        SecretBox,
        instance=SecretBox.random(),
        scope=Scope.singleton,
    )
    for service, impl in MEMORY_REPOSITORIES:
        container.register(service, instance=impl(), scope=Scope.singleton)
    container.register(
        BaseIntegrations,
        instance=MemoryIntegrations(),
        scope=Scope.singleton,
    )
    container.register(
        BaseDatabaseDumper,
        instance=NoDumper(),
        scope=Scope.singleton,
    )
    return container


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return init_dummy_container(tmp_path)


@pytest.fixture
def integrations(container: Container) -> MemoryIntegrations:
    return container.resolve(BaseIntegrations)


@pytest.fixture
def settings_service(container: Container) -> SettingsService:
    return container.resolve(SettingsService)


@pytest.fixture
def client(container: Container):
    app = create_app(lambda: container)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    resp = client.post(
        '/api/auth/setup',
        json={'username': 'admin', 'password': 'password123'},
    )
    assert resp.status_code == 201, resp.text
    client.headers['Authorization'] = f'Bearer {resp.json()["token"]}'
    return client
