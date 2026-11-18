"""Фоновое обновление данных и автоподнятие FunPay."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.usecases.errors import ConflictError
from app.usecases.friends import FriendsService
from app.usecases.journal import JOURNAL_SYNC_SEC, OrderJournalService
from app.usecases.raise_lots import RaiseService
from app.usecases.settings import SettingsService
from app.usecases.sync import SyncService

log = logging.getLogger('workers')
FRIENDS_CHECK_SEC = 600
RAISE_CHECK_SEC = 60
STATS_CHECK_SEC = 300


@dataclass
class Workers:
    settings: SettingsService
    friends: FriendsService
    raiser: RaiseService
    journal: OrderJournalService
    sales_sync: SyncService
    _tasks: list[asyncio.Task] = field(default_factory=list, init=False)

    def start(self) -> None:
        jobs = (
            ('Заказы FunPay', JOURNAL_SYNC_SEC, self._sync_journal, True),
            (
                'Статистика FunPay',
                STATS_CHECK_SEC,
                self._sync_statistics,
                True,
            ),
            ('Автоподнятие', RAISE_CHECK_SEC, self.raiser.tick, False),
            (
                'Обновление друзей',
                FRIENDS_CHECK_SEC,
                self.friends.refresh_if_stale,
                False,
            ),
        )
        self._tasks = [
            asyncio.create_task(self._periodic(name, interval, job, immediate))
            for name, interval, job, immediate in jobs
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.sales_sync.stop()

    async def _sync_journal(self) -> None:
        if (await self.settings.get()).funpay.golden_key:
            await self.journal.sync()

    async def _sync_statistics(self) -> None:
        if (await self.settings.get()).funpay.golden_key:
            await self.sales_sync.run_if_due()

    @staticmethod
    async def _periodic(
        name: str,
        interval: int,
        job: Callable[[], Awaitable[object]],
        immediate: bool,
    ) -> None:
        if not immediate:
            await asyncio.sleep(interval)
        while True:
            try:
                await job()
            except ConflictError:
                pass  # Уже запущено из интерфейса.
            except Exception as exc:
                log.warning('%s: %s', name, exc)
            await asyncio.sleep(interval)
