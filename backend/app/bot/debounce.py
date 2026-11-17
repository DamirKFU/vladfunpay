from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class _Pending:
    first_at: datetime
    last_at: datetime


@dataclass
class ChatDebouncer:
    """Склеивает несколько сообщений подряд в один ответ.

    Чат готов к ответу, когда покупатель молчит delay секунд или с первого
    неотвеченного сообщения прошло max_wait секунд (потолок ожидания).
    """

    _pending: dict[str, _Pending] = field(default_factory=dict)

    def touch(self, chat_id: str, now: datetime) -> None:
        item = self._pending.get(chat_id)
        if item is None:
            self._pending[chat_id] = _Pending(first_at=now, last_at=now)
        else:
            item.last_at = now

    def due(
        self,
        now: datetime,
        delay_sec: int,
        max_wait_sec: int,
    ) -> list[str]:
        ready = []
        for chat_id, item in self._pending.items():
            quiet = now - item.last_at >= timedelta(seconds=delay_sec)
            waited = now - item.first_at >= timedelta(seconds=max_wait_sec)
            if quiet or waited:
                ready.append(chat_id)
        for chat_id in ready:
            del self._pending[chat_id]
        return ready

    def pending(self) -> list[str]:
        return list(self._pending)
