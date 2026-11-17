"""Уведомления владельцу: ошибка инструмента, чат передан продавцу.

Если Telegram не привязан, бот просто отвечает покупателю как обычно,
а событие остаётся в логах. Одинаковые уведомления не чаще раза в
DEDUPE_MINUTES, чтобы покупатель, который шлёт кривую ссылку пять раз
подряд, не засыпал владельца сообщениями.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.integrations.notify.base import NotifyError
from app.integrations.provider import BaseIntegrations
from app.models.app_settings import AppSettings
from app.models.domain import Channel, Conversation, ToolCallTrace
from app.usecases.errors import ValidationError
from app.usecases.settings import SettingsService

log = logging.getLogger('alerts')
DEDUPE_MINUTES = 10


@dataclass
class OwnerAlerts:
    settings: SettingsService
    integrations: BaseIntegrations
    _sent: dict[str, datetime] = field(default_factory=dict, init=False)

    async def tool_errors(
        self,
        channel: Channel,
        conv: Conversation,
        calls: list[ToolCallTrace],
    ) -> int:
        s = await self.settings.get()
        if not s.telegram.notify_tool_errors:
            return 0
        sent = 0
        for call in calls:
            if not (isinstance(call.result, dict) and 'error' in call.result):
                continue
            text = (
                f'⚠️ Бот не смог выполнить действие\n'
                f'Инструмент: {call.name}\n'
                f'Ошибка: {call.result["error"]}\n'
                f'{self._where(channel, conv)}'
            )
            key = f'tool:{channel}:{conv.chat_id}:{call.name}'
            sent += await self._send(s, channel, key, text)
        return sent

    async def handoff(
        self,
        channel: Channel,
        conv: Conversation,
    ) -> int:
        s = await self.settings.get()
        if not s.telegram.notify_handoff:
            return 0
        text = (
            f'🙋 Чат передан вам\n'
            f'Причина: {conv.human_reason or "не указана"}\n'
            f'{self._where(channel, conv)}'
        )
        return await self._send(s, channel, f'handoff:{conv.chat_id}', text)

    async def test(self) -> None:
        s = await self.settings.get()
        notifier = self.integrations.notifier(s)
        if notifier is None:
            raise ValidationError('укажите токен бота и chat_id Telegram')
        try:
            await notifier.send('✅ FunPay Seller: уведомления работают')
        except NotifyError as e:
            raise ValidationError(str(e)) from e

    async def _send(
        self,
        s: AppSettings,
        channel: Channel,
        key: str,
        text: str,
    ) -> int:
        if channel == Channel.SANDBOX:
            if not s.telegram.notify_sandbox:
                log.info('Уведомление (песочница, не отправляем): %s', text)
                return 0
            text = '[песочница] ' + text
        notifier = self.integrations.notifier(s)
        if notifier is None:
            log.info(
                'Telegram не привязан, уведомление только в логах: %s', text
            )
            return 0
        now = datetime.now(timezone.utc)
        last = self._sent.get(key)
        if last and now - last < timedelta(minutes=DEDUPE_MINUTES):
            log.info('Уведомление пропущено (повтор): %s', key)
            return 0
        try:
            await notifier.send(text)
        except NotifyError as e:
            log.warning('Уведомление владельцу не ушло: %s', e)
            return 0
        self._sent[key] = now
        return 1

    @staticmethod
    def _where(channel: Channel, conv: Conversation) -> str:
        place = 'песочница' if channel == Channel.SANDBOX else 'FunPay'
        link = (
            f'\nhttps://funpay.com/chat/?node={conv.chat_id}'
            if channel == Channel.FUNPAY
            else ''
        )
        return (
            f'Покупатель: {conv.buyer_name} ({place}, чат {conv.chat_id})'
            + link
        )
