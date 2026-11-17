from dataclasses import dataclass, field

from app.integrations.notify.base import BaseNotifier, NotifyError


@dataclass
class MemoryNotifier(BaseNotifier):
    sent: list[str] = field(default_factory=list)
    fail: bool = False

    async def send(self, text: str) -> None:
        if self.fail:
            raise NotifyError('Telegram: тестовая ошибка')
        self.sent.append(text)
