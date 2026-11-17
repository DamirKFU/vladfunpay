"""Логи всего подряд, автоподнятие, запрет удаления, уведомления владельцу."""

import logging
from datetime import datetime, timedelta, timezone

from app.integrations.funpay.base import RaiseResult
from app.integrations.funpay.orders import order_from_export
from app.integrations.llm.base import LLMReply, ToolCall
from app.integrations.steam.web import access_token, explain_status
from app.models.domain import Channel, Relationship, SteamFriend
from app.repositories.base import BaseOrderRepository
from app.usecases.chats import SandboxService
from app.usecases.friends import FriendsService
from app.usecases.raise_lots import RaiseService

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def test_api_requests_and_errors_are_logged(auth_client, caplog):
    caplog.set_level(logging.INFO)
    auth_client.patch(
        '/api/settings',
        json={
            'funpay': {'golden_key': 'gk-very-secret-1'},
            'bot': {'max_tokens': 300},
        },
    )
    auth_client.post(
        '/api/users',
        json={'username': 'friend', 'password': 'short'},
    )
    auth_client.get('/api/bot/status')  # опрос — в лог не пишется

    text = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'API PATCH /api/settings → 200' in text
    assert 'Настройки изменены: bot.max_tokens, funpay.golden_key' in text
    assert 'gk-very-secret-1' not in text
    assert 'POST /api/users: пароль должен быть не короче 8' in text
    assert 'API POST /api/users → 422' in text
    assert '/api/bot/status' not in text


def test_frontend_errors_go_to_log(auth_client, caplog):
    caplog.set_level(logging.INFO)
    auth_client.post(
        '/api/logs/client',
        json={'message': 'TypeError: x is undefined', 'url': '/steam'},
    )
    assert any(
        r.name == 'frontend' and 'TypeError' in r.getMessage()
        for r in caplog.records
    )


def test_steam_401_explained_and_token_parsed():
    text = explain_status('ISteamUser/GetFriendList/v1', 401)
    assert 'список друзей скрыт' in text
    assert 'Приватность' in text
    assert access_token('76561198000000001%7C%7CeyJabc.def') == 'eyJabc.def'
    assert access_token('') == ''


async def test_removal_switch_blocks_everything(
    container,
    integrations,
    settings_service,
):
    s = await settings_service.get()
    s.steam.api_key, s.steam.steam_id = 'k', '76561198000000000'
    s.friends.allow_removal = False
    s.friends.auto_cleanup = True
    await settings_service.save(s)
    integrations.steam_gateway.friend_list = [
        SteamFriend(
            '76561198000000005', Relationship.FRIEND, friend_since=NOW
        ),
    ]
    service = container.resolve(FriendsService)
    result = await service.remove(['76561198000000005'])
    assert result[0]['error'] == 'удаление друзей отключено в настройках'
    assert await service.auto_cleanup() == []
    assert integrations.steam_gateway.removed == []


async def _sandbox_chat_with_order(container):
    service = container.resolve(SandboxService)
    conv = await service.create_chat('buyer_x')
    order = await service.create_order(conv.chat_id, None, 'Arcana', 749)
    return service, conv, order


async def _answer(bot_service, sandbox, chat_id):
    for chat in await sandbox.fetch_new_messages():
        await bot_service.store_incoming(chat, Channel.SANDBOX)
    return await bot_service.answer(sandbox, chat_id)


async def test_tool_error_notifies_owner_once(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
):
    s = await settings_service.get()
    s.telegram.notify_sandbox = True
    await settings_service.save(s)
    service, conv, _ = await _sandbox_chat_with_order(container)
    for _ in range(2):
        await service.say(conv.chat_id, 'вот ссылка: мусор')
        integrations.model.steps = [
            LLMReply(
                '',
                [
                    ToolCall(
                        '1',
                        'save_steam_link',
                        {'order_id': 'NOPE', 'link': 'x'},
                    )
                ],
            ),
            LLMReply('Пришлите, пожалуйста, ссылку ещё раз.'),
        ]
        trace = await _answer(bot_service, sandbox, conv.chat_id)
        assert trace.outcome == 'replied'  # покупателю ответ всё равно ушёл

    sent = integrations.owner_notifier.sent
    assert len(sent) == 1  # второй раз — повтор, не шлём
    assert sent[0].startswith('[песочница] ⚠️ Бот не смог выполнить')
    assert 'save_steam_link' in sent[0]
    assert 'buyer_x' in sent[0]


async def test_handoff_notifies_and_sandbox_is_quiet_by_default(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, _ = await _sandbox_chat_with_order(container)
    await service.say(conv.chat_id, 'хочу возврат')
    integrations.model.steps = [
        LLMReply('', [ToolCall('1', 'request_human', {'reason': 'возврат'})]),
        LLMReply('Передал продавцу.'),
    ]
    await _answer(bot_service, sandbox, conv.chat_id)
    # Песочница по умолчанию владельца не беспокоит.
    assert integrations.owner_notifier.sent == []


async def test_without_telegram_bot_just_replies(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
    caplog,
):
    caplog.set_level(logging.INFO)
    integrations.telegram_linked = False
    s = await settings_service.get()
    s.telegram.notify_sandbox = True
    await settings_service.save(s)
    service, conv, _ = await _sandbox_chat_with_order(container)
    await service.say(conv.chat_id, 'ссылка')
    integrations.model.steps = [
        LLMReply(
            '', [ToolCall('1', 'get_order_details', {'order_id': 'NOPE'})]
        ),
        LLMReply('Не нашёл такой заказ, уточните номер.'),
    ]
    trace = await _answer(bot_service, sandbox, conv.chat_id)
    assert trace.outcome == 'replied'
    assert any(
        'Telegram не привязан' in r.getMessage() for r in caplog.records
    )


async def test_auto_raise_schedule(
    container,
    integrations,
    settings_service,
    export_records,
):
    await container.resolve(BaseOrderRepository).upsert_many(
        [order_from_export(r) for r in export_records],
    )
    service = container.resolve(RaiseService)
    assert await service.tick(NOW) == []  # выключено по умолчанию

    s = await settings_service.get()
    s.funpay.auto_raise = True
    await settings_service.save(s)
    done = await service.tick(NOW)
    assert integrations.lot_raiser.calls == [41]  # Dota 2 из заказов
    assert done[0].next_at == NOW + timedelta(hours=4)

    await service.tick(NOW + timedelta(hours=1))  # рано
    assert integrations.lot_raiser.calls == [41]

    integrations.lot_raiser.result = RaiseResult(False, 'Подождите', 0)
    await service.tick(NOW + timedelta(hours=4, minutes=1))
    state = (await service.status())['categories'][0]
    assert state.ok is False
    assert state.next_at == NOW + timedelta(hours=4, minutes=31)

    s.funpay.raise_categories = [41, 210]
    await settings_service.save(s)
    await service.tick(NOW, force=True)
    assert integrations.lot_raiser.calls[-2:] == [41, 210]


def test_telegram_and_raise_api(auth_client, integrations):
    assert auth_client.post('/api/telegram/test').status_code == 200
    assert integrations.owner_notifier.sent[-1].startswith('✅')
    integrations.telegram_linked = False
    resp = auth_client.post('/api/telegram/test')
    assert resp.status_code == 422
    assert auth_client.get('/api/funpay/raise').json() == {
        'enabled': False,
        'categories': [],
    }
