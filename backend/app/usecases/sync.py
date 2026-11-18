"""Синхронизация продаж с FunPay через встроенную выгрузку.

Первый раз (в базе нет заказов) — выгрузка «за всё время». Дальше — с
даты последней оплаты, но не позже самого старого незакрытого заказа:
так заказ, оплаченный давно и закрытый вчера, тоже обновит статус.
"""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core import messages
from app.integrations.funpay.base import MarketplaceError
from app.integrations.funpay.orders import order_from_export
from app.integrations.provider import BaseIntegrations, NotConfiguredError
from app.models.domain import SyncRun, SyncStatus
from app.repositories.base import BaseOrderRepository, BaseSyncRunRepository
from app.usecases.errors import ConflictError
from app.usecases.settings import SettingsService

log = logging.getLogger('sync')
MSK = ZoneInfo('Europe/Moscow')
OVERLAP_DAYS = 1
STATS_SYNC_INTERVAL = timedelta(hours=1)


def sync_window(
    today: date,
    last_paid: datetime | None,
    oldest_open: datetime | None,
) -> tuple[date | None, date]:
    if last_paid is None:
        return None, today
    start = last_paid.astimezone(MSK).date()
    if oldest_open is not None:
        start = min(start, oldest_open.astimezone(MSK).date())
    return start - timedelta(days=OVERLAP_DAYS), today


@dataclass
class SyncService:
    settings: SettingsService
    orders: BaseOrderRepository
    runs: BaseSyncRunRepository
    integrations: BaseIntegrations
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _task: asyncio.Task[SyncRun] | None = field(default=None, init=False)

    async def start(self) -> SyncRun:
        """Создаёт запуск и выполняет его в фоне."""
        async with self._lock:
            if self._task is not None and not self._task.done():
                raise ConflictError(messages.SYNC_ALREADY_RUNNING)
            run = await self._new_run()
            self._task = asyncio.create_task(self.execute(run))
        return run

    async def run_now(self) -> SyncRun:
        await self.start()
        assert self._task is not None
        return await asyncio.shield(self._task)

    async def run_if_due(self) -> None:
        latest = await self.history(limit=1)
        if latest and latest[0].status == SyncStatus.DONE:
            finished_at = latest[0].finished_at
            if (
                finished_at
                and datetime.now(MSK) - finished_at < STATS_SYNC_INTERVAL
            ):
                return
        await self.run_now()

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _new_run(self) -> SyncRun:
        today = datetime.now(MSK).date()
        date_from, date_to = sync_window(
            today,
            await self.orders.max_paid_at(),
            await self.orders.min_paid_at('paid'),
        )
        run = SyncRun(
            id=uuid.uuid4().hex,
            status=SyncStatus.RUNNING,
            started_at=datetime.now(MSK),
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat(),
        )
        await self.runs.save(run)
        return run

    async def execute(self, run: SyncRun) -> SyncRun:
        try:
            try:
                settings = await self.settings.get()
                exporter = self.integrations.exporter(settings)
                records = await exporter.export(
                    date.fromisoformat(run.date_from)
                    if run.date_from
                    else None,
                    date.fromisoformat(run.date_to),
                )
                orders = [order_from_export(r) for r in records]
                run.fetched = len(records)
                run.upserted = await self.orders.upsert_many(orders)
                run.status = SyncStatus.DONE
                run.message = f'получено {run.fetched}'
                log.info(
                    'Синхронизация %s—%s: %d заказов',
                    run.date_from or 'всё время',
                    run.date_to,
                    run.fetched,
                )
            except (NotConfiguredError, MarketplaceError) as e:
                run.status, run.message = SyncStatus.ERROR, str(e)
                log.error('Синхронизация не удалась: %s', e)
            except Exception as e:
                run.status, run.message = SyncStatus.ERROR, str(e)
                log.exception('Синхронизация упала: %s', e)
        except asyncio.CancelledError:
            run.status, run.message = SyncStatus.ERROR, 'сервер остановлен'
            raise
        finally:
            run.finished_at = datetime.now(MSK)
            await self.runs.save(run)
        return run

    async def history(self, limit: int = 20) -> list[SyncRun]:
        return await self.runs.latest(limit)
