"""Логи приложения в MongoDB (для страницы «Логи» и выгрузки)."""

import asyncio
import logging
from datetime import datetime, timezone

from app.core.masking import masker
from app.models.domain import LogEntry
from app.repositories.base import BaseLogRepository

BATCH = 200
FLUSH_SEC = 1.0
QUEUE_MAX = 10_000
SKIP_LOGGERS = ('pymongo', 'httpx', 'httpcore', 'uvicorn.access', 'aiohttp')
EXTRA_KEYS = (
    'chat_id',
    'tokens',
    'order_id',
    'steam_id',
    'client',
    'user',
    'tool',
)


class QueueLogHandler(logging.Handler):
    """Кладёт записи в очередь; запись в базу — фоновой задачей."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self.loop = loop
        self.queue: asyncio.Queue[LogEntry] = asyncio.Queue(QUEUE_MAX)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(SKIP_LOGGERS):
            return
        try:
            text = masker.mask(record.getMessage())
            if record.exc_info:
                text += '\n' + masker.mask(self.format_exc(record))
            entry = LogEntry(
                ts=datetime.fromtimestamp(record.created, tz=timezone.utc),
                level=record.levelname,
                source=record.name,
                message=text,
                context={
                    k: getattr(record, k)
                    for k in EXTRA_KEYS
                    if hasattr(record, k)
                },
            )
            self.loop.call_soon_threadsafe(self._put, entry)
        except Exception:
            self.handleError(record)

    def _put(self, entry: LogEntry) -> None:
        if not self.queue.full():
            self.queue.put_nowait(entry)

    @staticmethod
    def format_exc(record: logging.LogRecord) -> str:
        return logging.Formatter().formatException(record.exc_info)


async def flush_forever(
    handler: QueueLogHandler,
    repository: BaseLogRepository,
) -> None:
    while True:
        batch = [await handler.queue.get()]
        try:
            async with asyncio.timeout(FLUSH_SEC):
                while len(batch) < BATCH:
                    batch.append(await handler.queue.get())
        except TimeoutError:
            pass
        try:
            await repository.insert_many(batch)
        except Exception as e:  # база недоступна — пишем только в stdout
            print(f'log sink: {e}')


class MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return masker.mask(super().format(record))


def setup_stdout_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        MaskingFormatter('%(asctime)s %(levelname)s %(name)s: %(message)s'),
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ('pymongo', 'httpx', 'httpcore', 'aiohttp'):
        logging.getLogger(name).setLevel(logging.WARNING)
