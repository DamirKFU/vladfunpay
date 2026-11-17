"""Фоновый цикл бота: опрос площадки, склейка сообщений, ответы."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.bot.debounce import ChatDebouncer
from app.bot.service import BotService, Clock, utc_now
from app.integrations.funpay.base import BaseMarketplace
from app.models.app_settings import AppSettings

log = logging.getLogger('bot.worker')

MarketplaceFactory = Callable[
    [AppSettings],
    Awaitable[BaseMarketplace | None],
]


@dataclass
class WorkerState:
    running: bool = False
    active: bool = False
    last_poll_at: datetime | None = None
    last_error: str = ''
    pending_chats: list[str] = field(default_factory=list)


@dataclass
class BotWorker:
    name: str
    service: BotService
    make_marketplace: MarketplaceFactory
    clock: Clock = utc_now
    tick_sec: float = 1.0
    state: WorkerState = field(default_factory=WorkerState)
    debouncer: ChatDebouncer = field(default_factory=ChatDebouncer)
    _marketplace: BaseMarketplace | None = field(default=None, init=False)
    _next_poll: float = field(default=0.0, init=False)

    async def run_forever(self) -> None:
        self.state.running = True
        try:
            while True:
                await self.tick()
                await asyncio.sleep(self.tick_sec)
        finally:
            self.state.running = False
            await self._drop_marketplace()

    async def tick(self) -> None:
        """Один шаг: опрос (если пора) и ответы в созревших чатах."""
        settings = await self.service.settings.get()
        try:
            marketplace = await self.make_marketplace(settings)
            if marketplace is not self._marketplace:
                await self._drop_marketplace()
                self._marketplace = marketplace
            self.state.active = marketplace is not None
            if marketplace is None:
                return
            loop_now = asyncio.get_running_loop().time()
            if loop_now >= self._next_poll:
                self._next_poll = loop_now + settings.bot.poll_interval_sec
                await self.poll(marketplace)
            await self.flush(marketplace, settings)
            self.state.last_error = ''
        except Exception as e:  # цикл не должен падать от одной ошибки
            self.state.last_error = str(e)
            log.exception('Воркер %s: %s', self.name, e)

    async def poll(self, marketplace: BaseMarketplace) -> None:
        chats = await marketplace.fetch_new_messages()
        self.state.last_poll_at = self.clock()
        for chat in chats:
            if await self.service.store_incoming(chat, marketplace.channel):
                self.debouncer.touch(chat.chat_id, self.clock())
        self.state.pending_chats = self.debouncer.pending()

    async def flush(
        self,
        marketplace: BaseMarketplace,
        settings: AppSettings,
    ) -> None:
        due = self.debouncer.due(
            self.clock(),
            settings.bot.reply_delay_sec,
            settings.bot.max_wait_sec,
        )
        for chat_id in due:
            trace = await self.service.answer(marketplace, chat_id)
            if trace and trace.outcome == 'discarded':
                self.debouncer.touch(chat_id, self.clock())
        self.state.pending_chats = self.debouncer.pending()

    async def _drop_marketplace(self) -> None:
        if self._marketplace is not None:
            await self._marketplace.close()
            self._marketplace = None
