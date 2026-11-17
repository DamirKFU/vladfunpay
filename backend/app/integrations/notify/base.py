from abc import ABC, abstractmethod


class NotifyError(RuntimeError):
    pass


class BaseNotifier(ABC):
    """Канал уведомлений владельцу (сейчас — Telegram)."""

    @abstractmethod
    async def send(self, text: str) -> None: ...
