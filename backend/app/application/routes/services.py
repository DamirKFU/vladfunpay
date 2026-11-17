"""Автоподнятие лотов, Telegram и ошибки фронта в общий лог."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.application.deps import current_user, resolve
from app.integrations.notify.base import NotifyError
from app.integrations.notify.telegram import find_chats
from app.models.domain import User
from app.usecases.alerts import OwnerAlerts
from app.usecases.errors import ValidationError
from app.usecases.raise_lots import RaiseService
from app.usecases.settings import SettingsService

router = APIRouter(dependencies=[Depends(current_user)])
front_log = logging.getLogger('frontend')


class ClientErrorSchema(BaseModel):
    message: str = Field(max_length=2000)
    url: str = Field(default='', max_length=500)
    stack: str = Field(default='', max_length=4000)


@router.get('/funpay/raise', tags=['funpay'], summary='Автоподнятие')
async def raise_status(
    service: RaiseService = Depends(resolve(RaiseService)),
) -> dict:
    return await service.status()


@router.post('/funpay/raise', tags=['funpay'], summary='Поднять лоты сейчас')
async def raise_now(
    service: RaiseService = Depends(resolve(RaiseService)),
) -> dict:
    await service.tick(force=True)
    return await service.status()


@router.post('/telegram/test', tags=['telegram'], summary='Тест уведомлений')
async def telegram_test(
    alerts: OwnerAlerts = Depends(resolve(OwnerAlerts)),
) -> dict:
    await alerts.test()
    return {'ok': True}


@router.post(
    '/telegram/detect-chat',
    tags=['telegram'],
    summary='Найти chat_id: напишите боту /start и вызовите',
)
async def telegram_detect(
    settings: SettingsService = Depends(resolve(SettingsService)),
) -> dict:
    s = await settings.get()
    if not s.telegram.bot_token:
        raise ValidationError('сначала сохраните токен бота')
    try:
        chats = await find_chats(s.telegram.bot_token)
    except NotifyError as e:
        raise ValidationError(str(e)) from e
    if not chats:
        raise ValidationError(
            'бот ещё не получал сообщений: напишите ему /start в Telegram',
        )
    await settings.update({'telegram': {'chat_id': chats[-1]['chat_id']}})
    return {'chats': chats, 'chat_id': chats[-1]['chat_id']}


@router.post('/logs/client', tags=['logs'], summary='Ошибка во фронте')
async def client_error(
    schema: ClientErrorSchema,
    user: User = Depends(current_user),
) -> dict:
    front_log.warning(
        'Фронт: %s (%s)%s',
        schema.message,
        schema.url,
        f'\n{schema.stack}' if schema.stack else '',
        extra={'user': user.username},
    )
    return {'ok': True}
