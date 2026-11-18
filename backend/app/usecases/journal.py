"""Снимок открытых и последних заказов продавца."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.integrations.provider import BaseIntegrations, NotConfiguredError
from app.models.domain import SalesSnapshot
from app.repositories.base import BaseSalesSnapshotRepository
from app.usecases.errors import ConflictError, ExternalServiceError
from app.usecases.settings import SettingsService

log = logging.getLogger('journal')
JOURNAL_SYNC_SEC = 120
SYNC_TIMEOUT_SEC = 90


@dataclass
class OrderJournalService:
    repository: BaseSalesSnapshotRepository
    settings: SettingsService
    integrations: BaseIntegrations
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _error: str = field(default='', init=False)

    async def sync(self) -> SalesSnapshot:
        if self._lock.locked():
            raise ConflictError('Обновление заказов уже идёт.')
        async with self._lock:
            try:
                settings = await self.settings.get()
                reader = self.integrations.sales(settings)
                try:
                    async with asyncio.timeout(SYNC_TIMEOUT_SEC):
                        items = await reader.sales()
                finally:
                    await reader.close()
                snapshot = SalesSnapshot(datetime.now(timezone.utc), items)
                await self.repository.save(snapshot)
            except NotConfiguredError:
                self._error = 'Укажите golden_key в настройках FunPay.'
                raise
            except Exception as exc:
                self._error = 'Не удалось обновить заказы с FunPay.'
                log.exception(self._error)
                raise ExternalServiceError(self._error) from exc

            self._error = ''
            log.info('Заказы FunPay обновлены: %d', len(items))
            return snapshot

    async def view(self) -> dict:
        snapshot = await self.repository.load()
        return {
            'items': snapshot.items if snapshot else [],
            'refreshed_at': snapshot.refreshed_at if snapshot else None,
            'refreshing': self._lock.locked(),
            'error': self._error,
            'interval_seconds': JOURNAL_SYNC_SEC,
        }
