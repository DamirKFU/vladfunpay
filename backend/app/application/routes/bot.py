"""Бот: состояние, переписка, ассортимент и песочница."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.application.deps import current_user, resolve
from app.application.schemas import (
    FriendshipSchema,
    OfferSchema,
    OrderStatusSchema,
    SandboxChatSchema,
    SandboxMessageSchema,
    SandboxOrderSchema,
)
from app.bot.prompt import DEFAULT_STYLE, TOOL_RULES, compose_system_prompt
from app.integrations.funpay.sandbox import SandboxMarketplace
from app.integrations.provider import NotConfiguredError
from app.models.domain import Channel, Offer
from app.repositories.base import BaseUsageRepository
from app.usecases.chats import ChatService, SandboxService
from app.usecases.errors import ValidationError
from app.usecases.settings import SettingsService
from app.workers.runtime import FunPayMarketplaceProvider, Workers

router = APIRouter(dependencies=[Depends(current_user)])
MSK = ZoneInfo('Europe/Moscow')


@router.get('/bot/status', tags=['bot'], summary='Состояние бота')
async def bot_status(
    workers: Workers = Depends(resolve(Workers)),
    usage: BaseUsageRepository = Depends(resolve(BaseUsageRepository)),
    settings: SettingsService = Depends(resolve(SettingsService)),
) -> dict:
    s = await settings.get()
    day = datetime.now(MSK).date().isoformat()
    return {
        'enabled': s.bot.enabled,
        'funpay': workers.funpay.state,
        'sandbox': workers.sandbox_worker.state,
        'tokens_today': await usage.tokens(day),
        'daily_token_limit': s.bot.daily_token_limit,
        'llm_configured': bool(s.yandex.api_key and s.yandex.folder_id),
        'funpay_configured': bool(s.funpay.golden_key),
    }


@router.get('/bot/prompt', tags=['bot'], summary='Промпт бота')
async def bot_prompt(
    settings: SettingsService = Depends(resolve(SettingsService)),
) -> dict:
    s = await settings.get()
    return {
        'tool_rules': TOOL_RULES,
        'default_style': DEFAULT_STYLE,
        'composed': compose_system_prompt(s.bot),
    }


@router.get(
    '/bot/{channel}/conversations',
    tags=['bot'],
    summary='Чаты бота',
)
async def conversations(
    channel: Channel,
    service: ChatService = Depends(resolve(ChatService)),
):
    return await service.conversations(channel)


@router.get(
    '/bot/{channel}/conversations/{chat_id}',
    tags=['bot'],
    summary='Переписка и разбор ответов',
)
async def conversation(
    channel: Channel,
    chat_id: str,
    service: ChatService = Depends(resolve(ChatService)),
):
    return await service.view(channel, chat_id)


@router.post(
    '/bot/{channel}/conversations/{chat_id}/resume',
    tags=['bot'],
    summary='Вернуть чат боту',
)
async def resume(
    channel: Channel,
    chat_id: str,
    service: ChatService = Depends(resolve(ChatService)),
) -> dict:
    await service.resume(channel, chat_id)
    return {'ok': True}


@router.get('/bot/{channel}/assortment', tags=['bot'], summary='Лоты')
async def assortment(
    channel: Channel,
    settings: SettingsService = Depends(resolve(SettingsService)),
    provider: FunPayMarketplaceProvider = Depends(
        resolve(FunPayMarketplaceProvider),
    ),
    sandbox: SandboxMarketplace = Depends(resolve(SandboxMarketplace)),
) -> list[Offer]:
    if channel == Channel.SANDBOX:
        return await sandbox.offers()
    s = await settings.get()
    s.bot.enabled = True  # смотреть лоты можно и при выключенном боте
    try:
        marketplace = await provider(s)
    except NotConfiguredError as e:
        raise ValidationError(str(e)) from e
    if marketplace is None:
        raise ValidationError('не задан golden_key FunPay')
    return await marketplace.offers()


@router.post('/sandbox/chats', tags=['sandbox'], summary='Новый покупатель')
async def sandbox_chat(
    schema: SandboxChatSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
):
    return await service.create_chat(schema.buyer_name)


@router.post(
    '/sandbox/chats/{chat_id}/messages',
    tags=['sandbox'],
    summary='Написать боту от имени покупателя',
)
async def sandbox_say(
    chat_id: str,
    schema: SandboxMessageSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
):
    return await service.say(chat_id, schema.text)


@router.post(
    '/sandbox/chats/{chat_id}/reset',
    tags=['sandbox'],
    summary='Очистить переписку',
)
async def sandbox_reset(
    chat_id: str,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> dict:
    await service.reset(chat_id)
    return {'ok': True}


@router.get('/sandbox/orders', tags=['sandbox'], summary='Тестовые заказы')
async def sandbox_orders(
    chat_id: str | None = None,
    service: SandboxService = Depends(resolve(SandboxService)),
):
    return await service.orders(chat_id)


@router.post('/sandbox/orders', tags=['sandbox'], summary='Сделать заказ')
async def sandbox_create_order(
    schema: SandboxOrderSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
):
    return await service.create_order(
        schema.chat_id,
        schema.offer_id,
        schema.title,
        schema.price,
    )


@router.patch(
    '/sandbox/orders/{order_id}',
    tags=['sandbox'],
    summary='Статус заказа',
)
async def sandbox_order_status(
    order_id: str,
    schema: OrderStatusSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> dict:
    await service.set_order_status(order_id, schema.status)
    return {'ok': True}


@router.get('/sandbox/offers', tags=['sandbox'], summary='Тестовые лоты')
async def sandbox_offers(
    service: SandboxService = Depends(resolve(SandboxService)),
) -> list[Offer]:
    return await service.offers()


@router.put('/sandbox/offers', tags=['sandbox'], summary='Сохранить лот')
async def sandbox_save_offer(
    schema: OfferSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> Offer:
    return await service.save_offer(Offer(**schema.model_dump()))


@router.delete(
    '/sandbox/offers/{offer_id}',
    tags=['sandbox'],
    summary='Удалить лот',
)
async def sandbox_delete_offer(
    offer_id: str,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> dict:
    await service.delete_offer(offer_id)
    return {'ok': True}


@router.get(
    '/sandbox/chats/{chat_id}/friendship',
    tags=['sandbox'],
    summary='Симуляция дружбы Steam',
)
async def sandbox_friendship(
    chat_id: str,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> dict:
    return await service.friendship(chat_id)


@router.put(
    '/sandbox/chats/{chat_id}/friendship',
    tags=['sandbox'],
    summary='Задать дружбу Steam для теста сроков выдачи',
)
async def sandbox_set_friendship(
    chat_id: str,
    schema: FriendshipSchema,
    service: SandboxService = Depends(resolve(SandboxService)),
) -> dict:
    return await service.set_friendship(
        chat_id,
        schema.relationship,
        schema.since,
    )
