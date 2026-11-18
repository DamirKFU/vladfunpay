"""Автоподнятие лотов, ошибки фронта в общий лог."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.application.deps import current_user, resolve
from app.models.domain import User
from app.usecases.raise_lots import RaiseService

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
