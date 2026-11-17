"""Уведомления в Telegram через Bot API (свой бот от @BotFather)."""

import logging
from dataclasses import dataclass

import httpx

from app.integrations.notify.base import BaseNotifier, NotifyError

log = logging.getLogger('telegram')
API = 'https://api.telegram.org'
MAX_LEN = 4000


@dataclass
class TelegramNotifier(BaseNotifier):
    bot_token: str
    chat_id: str

    async def send(self, text: str) -> None:
        url = f'{API}/bot{self.bot_token}/sendMessage'
        body = {
            'chat_id': self.chat_id,
            'text': text[:MAX_LEN],
            'disable_web_page_preview': True,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(url, json=body)
        except httpx.HTTPError as e:
            log.warning('Telegram: сеть: %s', e)
            raise NotifyError(f'Telegram недоступен: {e}') from e
        data = _json(resp)
        if resp.status_code != 200 or not data.get('ok'):
            detail = data.get('description') or f'HTTP {resp.status_code}'
            log.warning('Telegram: не отправлено: %s', detail)
            raise NotifyError(f'Telegram: {detail}')
        log.info('Telegram: уведомление отправлено')


async def find_chats(bot_token: str) -> list[dict]:
    """Чаты, которые писали боту: чтобы узнать свой chat_id.

    Владелец пишет своему боту /start, затем нажимает «Найти chat_id».
    """
    url = f'{API}/bot{bot_token}/getUpdates'
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise NotifyError(f'Telegram недоступен: {e}') from e
    data = _json(resp)
    if not data.get('ok'):
        raise NotifyError(
            f'Telegram: {data.get("description") or resp.status_code}',
        )
    chats: dict[str, dict] = {}
    for update in data.get('result', []):
        message = update.get('message') or update.get('my_chat_member') or {}
        chat = message.get('chat') or {}
        if chat.get('id') is not None:
            name = chat.get('username') or chat.get('title') or ''
            chats[str(chat['id'])] = {'chat_id': str(chat['id']), 'name': name}
    return list(chats.values())


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
