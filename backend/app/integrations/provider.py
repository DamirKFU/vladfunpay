"""Сборка клиентов внешних сервисов из настроек, введённых во фронте."""

from abc import ABC, abstractmethod

from app.core import messages
from app.integrations.funpay.base import (
    BaseLotRaiser,
    BaseMarketplace,
    BaseOrderExporter,
)
from app.integrations.funpay.engine import FunPayMarketplace
from app.integrations.funpay.exports import FunPayExporter
from app.integrations.llm.base import BaseLLM
from app.integrations.llm.yandex import YandexLLM
from app.integrations.notify.base import BaseNotifier
from app.integrations.notify.telegram import TelegramNotifier
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
    def funpay(
        self,
        s: AppSettings,
        subcategories: list[int],
    ) -> BaseMarketplace: ...

    @abstractmethod
    def steam(self, s: AppSettings) -> BaseSteamGateway: ...

    @abstractmethod
    def llm(self, s: AppSettings) -> BaseLLM: ...

    @abstractmethod
    def raiser(self, s: AppSettings) -> BaseLotRaiser: ...

    @abstractmethod
    def notifier(self, s: AppSettings) -> BaseNotifier | None:
        """None — Telegram не привязан."""


class LiveIntegrations(BaseIntegrations):
    def exporter(self, s: AppSettings) -> BaseOrderExporter:
        require(golden_key=s.funpay.golden_key)
        return FunPayExporter(s.funpay.golden_key, s.funpay.user_agent)

    def funpay(
        self,
        s: AppSettings,
        subcategories: list[int],
    ) -> BaseMarketplace:
        require(golden_key=s.funpay.golden_key)
        return FunPayMarketplace(
            golden_key=s.funpay.golden_key,
            user_agent=s.funpay.user_agent,
            subcategories=s.funpay.offer_subcategories or subcategories,
        )

    def steam(self, s: AppSettings) -> BaseSteamGateway:
        require(steam_api_key=s.steam.api_key, steam_id=s.steam.steam_id)
        return SteamWebGateway(
            api_key=s.steam.api_key,
            steam_id=s.steam.steam_id,
            login_secure=s.steam.login_secure,
            session_id=s.steam.session_id,
            user_agent=s.funpay.user_agent,
        )

    def llm(self, s: AppSettings) -> BaseLLM:
        if not (s.yandex.api_key and s.yandex.folder_id):
            raise NotConfiguredError(messages.LLM_NOT_CONFIGURED)
        return YandexLLM(
            api_key=s.yandex.api_key,
            folder_id=s.yandex.folder_id,
            model=s.yandex.model,
            base_url=s.yandex.base_url,
            temperature=s.yandex.temperature,
        )

    def raiser(self, s: AppSettings) -> BaseLotRaiser:
        require(golden_key=s.funpay.golden_key)
        return FunPayMarketplace(
            golden_key=s.funpay.golden_key,
            user_agent=s.funpay.user_agent,
            subcategories=[],
        )

    def notifier(self, s: AppSettings) -> BaseNotifier | None:
        if not (s.telegram.bot_token and s.telegram.chat_id):
            return None
        return TelegramNotifier(s.telegram.bot_token, s.telegram.chat_id)
