"""Отчёт по продажам, логи и выгрузка базы."""

import io
import json
import zipfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO

from app.models.domain import LogEntry
from app.report.render import render_report
from app.repositories.base import (
    BaseLogRepository,
    BaseOrderRepository,
    BaseUserRepository,
)
from app.usecases.settings import SettingsService

LOG_EXPORT_LIMIT = 200_000


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def to_jsonl(items: list[dict[str, Any]]) -> bytes:
    return ''.join(
        json.dumps(i, ensure_ascii=False, default=_json_default) + '\n'
        for i in items
    ).encode()


class BaseDatabaseDumper(ABC):
    @abstractmethod
    async def dump(self, archive: zipfile.ZipFile) -> list[str]:
        """Пишет коллекции в архив, возвращает их имена."""


@dataclass(frozen=True)
class ReportService:
    orders: BaseOrderRepository

    async def html(self) -> str:
        return render_report(await self.orders.list_all())


@dataclass(frozen=True)
class LogService:
    logs: BaseLogRepository

    async def query(
        self,
        level: str | None,
        source: str | None,
        search: str | None,
        hours: int | None,
        limit: int,
    ) -> list[LogEntry]:
        since = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
            if hours
            else None
        )
        return await self.logs.query(level, source, search, since, limit)

    async def sources(self) -> list[str]:
        return await self.logs.sources()

    async def export(
        self,
        level: str | None,
        source: str | None,
        hours: int | None,
    ) -> bytes:
        entries = await self.query(
            level, source, None, hours, LOG_EXPORT_LIMIT
        )
        return to_jsonl([asdict(e) for e in reversed(entries)])


@dataclass(frozen=True)
class DatabaseExportService:
    dumper: BaseDatabaseDumper
    users: BaseUserRepository
    settings: SettingsService

    async def export(self, out: BinaryIO) -> None:
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            names = await self.dumper.dump(archive)
            users = [
                {'username': u.username, 'created_at': u.created_at}
                for u in await self.users.list()
            ]
            archive.writestr('users.jsonl', to_jsonl(users))
            # Секреты заменены на признак «задан», ключи не уходят наружу.
            archive.writestr(
                'settings.json',
                json.dumps(
                    await self.settings.public(), ensure_ascii=False, indent=2
                ),
            )
            manifest = {
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'collections': names + ['users', 'settings'],
            }
            archive.writestr('manifest.json', json.dumps(manifest, indent=2))

    async def export_bytes(self) -> bytes:
        buffer = io.BytesIO()
        await self.export(buffer)
        return buffer.getvalue()
