"""Фоновые задачи процесса: два цикла бота, запись логов, автоочистка."""

import asyncio
import logging
from dataclasses import dataclass, field

from app.bot.service import BotService
from app.integrations.funpay.base import BaseMarketplace
from app.integrations.funpay.sandbox import SandboxMarketplace
from app.integrations.provider import BaseIntegrations
from app.models.app_settings import AppSettings
from app.repositories.base import BaseOrderRepository
from app.usecases.friends import FriendsService
from app.usecases.raise_lots import RaiseService
from app.workers.bot_worker import BotWorker

log = logging.getLogger('workers')
CLEANUP_EVERY_SEC = 6 * 3600
FRIENDS_CHECK_SEC = 600
RAISE_CHECK_SEC = 60


@dataclass
class FunPayMarketplaceProvider:
    """Отдаёт клиент FunPay, пока бот включён; пересоздаёт при смене ключа."""

    integrations: BaseIntegrations
    orders: BaseOrderRepository
    _key: tuple[str, str] | None = field(default=None, init=False)
    _current: BaseMarketplace | None = field(default=None, init=False)

    async def __call__(self, s: AppSettings) -> BaseMarketplace | None:
        if not (s.bot.enabled and s.funpay.golden_key):
            self._key, self._current = None, None
            return None
        key = (s.funpay.golden_key, s.funpay.user_agent)
        if key != self._key or self._current is None:
            self._current = self.integrations.funpay(
                s,
                await self.orders.node_ids(),
            )
            self._key = key
        return self._current


@dataclass
class Workers:
    bot_service: BotService
    sandbox: SandboxMarketplace
    funpay_provider: FunPayMarketplaceProvider
    friends: FriendsService
    raiser: RaiseService
    funpay: BotWorker | None = field(default=None, init=False)
    sandbox_worker: BotWorker | None = field(default=None, init=False)
    _tasks: list[asyncio.Task] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.funpay = BotWorker(
            name='funpay',
            service=self.bot_service,
            make_marketplace=self.funpay_provider,
        )
        self.sandbox_worker = BotWorker(
            name='sandbox',
            service=self.bot_service,
            make_marketplace=self._sandbox,
            tick_sec=0.5,
        )

    async def _sandbox(self, _: AppSettings) -> BaseMarketplace:
        return self.sandbox

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self.funpay.run_forever()),
            asyncio.create_task(self.sandbox_worker.run_forever()),
            asyncio.create_task(self._cleanup_forever()),
            asyncio.create_task(self._refresh_friends_forever()),
            asyncio.create_task(self._raise_forever()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _raise_forever(self) -> None:
        """Автоподнятие лотов: проверка раз в минуту, поднятие по сроку."""
        while True:
            await asyncio.sleep(RAISE_CHECK_SEC)
            try:
                await self.raiser.tick()
            except Exception as e:
                log.warning('Автоподнятие: %s', e)

    async def _refresh_friends_forever(self) -> None:
        """Друзья из Steam раз в refresh_hours — для сроков выдачи подарков."""
        while True:
            await asyncio.sleep(FRIENDS_CHECK_SEC)
            try:
                if await self.friends.refresh_if_stale():
                    log.info('Друзья Steam обновлены по расписанию')
            except Exception as e:
                log.warning('Обновление друзей Steam: %s', e)

    async def _cleanup_forever(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_EVERY_SEC)
            try:
                removed = await self.friends.auto_cleanup()
                if removed:
                    log.info('Автоочистка друзей: %s', removed)
            except Exception as e:
                log.warning('Автоочистка друзей: %s', e)
