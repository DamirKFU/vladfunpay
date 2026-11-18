"""Сборка клиентов внешних сервисов из настроек, введённых во фронте."""

from abc import ABC, abstractmethod

from app.core import messages
from app.integrations.funpay.base import (
    BaseLotRaiser,
    BaseOrderExporter,
    SalesReader,
)
from app.integrations.funpay.engine import FunPayMarketplace
from app.integrations.funpay.exports import FunPayExporter
from app.integrations.steam.base import BaseSteamGateway
from app.integrations.steam.web import SteamWebGateway
from app.models.app_settings import AppSettings


class NotConfiguredError(RuntimeError):
    pass


def require(**values: str) -> None:
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise NotConfiguredError(
            messages.SETTINGS_NOT_CONFIGURED.format(', '.join(missing)),
        )


class BaseIntegrations(ABC):
    @abstractmethod
    def exporter(self, s: AppSettings) -> BaseOrderExporter: ...

    @abstractmethod
    def sales(self, s: AppSettings) -> SalesReader: ...

    @abstractmethod
    def steam(self, s: AppSettings) -> BaseSteamGateway: ...

    @abstractmethod
    def raiser(self, s: AppSettings) -> BaseLotRaiser: ...


class LiveIntegrations(BaseIntegrations):
    def exporter(self, s: AppSettings) -> BaseOrderExporter:
        require(golden_key=s.funpay.golden_key)
        return FunPayExporter(s.funpay.golden_key, s.funpay.user_agent)

    def steam(self, s: AppSettings) -> BaseSteamGateway:
        require(steam_api_key=s.steam.api_key, steam_id=s.steam.steam_id)
        return SteamWebGateway(
            api_key=s.steam.api_key,
            steam_id=s.steam.steam_id,
            login_secure=s.steam.login_secure,
            user_agent=s.funpay.user_agent,
        )

    def sales(self, s: AppSettings) -> SalesReader:
        return self._funpay(s)

    def raiser(self, s: AppSettings) -> BaseLotRaiser:
        return self._funpay(s)

    def _funpay(self, s: AppSettings) -> FunPayMarketplace:
        require(golden_key=s.funpay.golden_key)
        return FunPayMarketplace(
            golden_key=s.funpay.golden_key,
            user_agent=s.funpay.user_agent,
        )
