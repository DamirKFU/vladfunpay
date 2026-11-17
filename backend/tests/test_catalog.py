"""Типы товаров, каталог лотов, очередь подарков, аккаунты в автовыдачу."""

import logging
from datetime import datetime, timedelta, timezone

from app.bot.catalog import (
    find_lot,
    order_type,
    parse_classification,
)
from app.bot.delivery import plan_delivery, schedule_gifts
from app.integrations.llm.base import LLMReply, ToolCall
from app.integrations.steam.friendship import Friendship
from app.integrations.steam.links import parse_steam_link
from app.models.app_settings import CatalogSettings
from app.models.domain import (
    Channel,
    LotRecord,
    Offer,
    OpenOrder,
    Relationship,
)
from app.repositories.base import BaseLotRepository, BaseSandboxRepository
from app.usecases.chats import SandboxService
from app.usecases.lots import LotCatalogService, account_line

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
PROFILE = 'https://steamcommunity.com/profiles/76561198000000001'
CATALOG = CatalogSettings()
GIFT = next(t for t in CATALOG.types if t.kind == 'gift')
TRADE = next(t for t in CATALOG.types if t.kind == 'trade')
ACCOUNT = next(t for t in CATALOG.types if t.kind == 'account')


def order(order_id='A1', title='Arcana Pudge', buyer=1):
    return OpenOrder(
        order_id,
        title,
        749.0,
        buyer,
        f'b{buyer}',
        created_at=NOW - timedelta(hours=1),
    )


def friends_since(days):
    return Friendship(Relationship.FRIEND, NOW - timedelta(days=days), NOW)


def lot(lot_id, title, type_id, description=''):
    return LotRecord(Channel.SANDBOX, lot_id, title, description, type_id)


# --- тип заказа ------------------------------------------------------------


def test_order_type_comes_from_lot_then_keywords_then_default():
    lots = [
        lot('1', 'Arcana Pudge', 'steam_trade'),
        lot('2', 'Аркана на Пуджа — подарком', 'dota_gift'),
    ]
    assert order_type(CATALOG, 'arcana   pudge', lots).id == 'steam_trade'
    assert find_lot('Dota 2, Arcana Pudge, 1 шт.', lots).lot_id == '1'
    assert order_type(CATALOG, 'Аккаунт 5000 MMR', []).id == 'dota_account'
    assert order_type(CATALOG, 'Непонятно что', []).id == 'dota_gift'


def test_parse_ai_classification():
    ok = parse_classification(
        CATALOG,
        '```json\n{"type_id": "dota_account", '
        '"reason": "логин и пароль"}\n```',
    )
    assert ok == ('dota_account', 'логин и пароль')
    assert parse_classification(CATALOG, '{"type_id": "nope"}') is None
    assert parse_classification(CATALOG, 'не знаю') is None


# --- очередь подарков с лимитом в день --------------------------------------


def test_gift_queue_respects_per_day_limit():
    link = parse_steam_link(PROFILE)
    plans = [
        plan_delivery(order(f'R{i}'), GIFT, link, friends_since(40), NOW)
        for i in range(10)  # 10 уже можно дарить, а в день — 8
    ]
    plans.append(
        plan_delivery(order('LATE'), GIFT, link, friends_since(29), NOW),
    )
    plans.append(
        plan_delivery(order('NOLINK'), GIFT, None, Friendship(None), NOW)
    )
    plans.append(
        plan_delivery(order('KEY', 'key'), TRADE, None, Friendship(None), NOW)
    )
    queue = schedule_gifts(plans, NOW)

    assert queue['R0']['estimated_send_date'] == '2026-11-17'
    assert queue['R7']['estimated_send_date'] == '2026-11-17'
    assert queue['R8']['estimated_send_date'] == '2026-11-18'  # сдвиг
    assert queue['R9']['days_until_send'] == 1
    # Через день его можно дарить, но 18-го уже 2 из 8 — успевает.
    assert queue['LATE']['estimated_send_date'] == '2026-11-18'
    assert queue['LATE']['position'] == 11
    assert queue['NOLINK']['estimated_send_date'] is None
    assert queue['NOLINK']['open_gift_orders'] == 12
    assert 'KEY' not in queue


def test_account_plan_never_carries_credentials():
    plan = plan_delivery(
        order(title='Аккаунт'), ACCOUNT, None, Friendship(None), NOW
    )
    assert plan.status == 'delivered_automatically_by_funpay'
    assert plan.info['login_problems'] == 'call request_human'


# --- каталог лотов в песочнице --------------------------------------------


async def _sandbox_lots(container):
    repo = container.resolve(BaseSandboxRepository)
    await repo.save_offer(
        Offer(
            'lot1',
            'Аркана Пудж',
            749,
            3,
            description='Отправлю подарком в Steam',
        )
    )
    await repo.save_offer(
        Offer(
            'lot2',
            'Dota 2 высокий ранг',
            2500,
            0,
            description='Полный доступ к профилю сразу после оплаты',
        )
    )
    await repo.save_offer(
        Offer(
            'lot3',
            'Набор Мистический',
            300,
            5,
            description='Передача через трейд',
        )
    )
    return container.resolve(LotCatalogService)


async def test_sync_classifies_by_keywords_and_ai(container, integrations):
    service = await _sandbox_lots(container)
    # «Аркана Пудж»: ключей нет ни в названии, ни в описании «подарком»?
    # «подарк» есть в описании — сработают слова-ключи. «Мистический» —
    # ключ «трейд». лот с высоким рангом — ключей нет, решает ИИ.
    integrations.model.steps = [
        LLMReply(
            '{"type_id": "dota_account", "reason": "логин и пароль"}',
            tokens=40,
        ),
    ]
    lots = {lot.lot_id: lot for lot in await service.sync(Channel.SANDBOX)}
    assert (lots['lot1'].type_id, lots['lot1'].assigned_by) == (
        'dota_gift',
        'keywords',
    )
    assert (lots['lot2'].type_id, lots['lot2'].assigned_by) == (
        'dota_account',
        'ai',
    )
    assert lots['lot3'].type_id == 'steam_trade'


async def test_manual_type_survives_resync_and_can_reset(
    container,
    integrations,
):
    service = await _sandbox_lots(container)
    integrations.model.steps = [LLMReply('{"type_id": "dota_account"}')]
    await service.sync(Channel.SANDBOX)
    await service.set_type(Channel.SANDBOX, 'lot1', 'manual')
    await service.sync(Channel.SANDBOX)
    repo = container.resolve(BaseLotRepository)
    assert (await repo.get(Channel.SANDBOX, 'lot1')).type_id == 'manual'

    reset = await service.set_type(Channel.SANDBOX, 'lot1', None)
    assert (reset.type_id, reset.assigned_by) == ('dota_gift', 'keywords')


def test_account_line_one_line_per_account():
    line = account_line(
        {
            'login': 'user1',
            'password': 'p@ss\nword',
            'email': 'a@b.c',
            'email_password': '',
            'note': '',
        }
    )
    assert line == 'Логин: user1 | Пароль: p@ss word | Почта: a@b.c'
    assert '\n' not in line


async def test_accounts_go_to_auto_delivery_and_are_not_stored(
    container,
    integrations,
    caplog,
):
    caplog.set_level(logging.DEBUG)
    service = await _sandbox_lots(container)
    integrations.model.steps = [LLMReply('{"type_id": "dota_account"}')]
    await service.sync(Channel.SANDBOX)
    result = await service.add_accounts(
        Channel.SANDBOX,
        'lot2',
        [
            {'login': 'acc_login_1', 'password': 'Secret-Pass-1'},
            {
                'login': 'acc_login_2',
                'password': 'Secret-Pass-2',
                'email': 'mail@x.y',
                'email_password': 'Mail-Pass',
            },
        ],
    )
    assert result.amount == 2
    assert result.auto_delivery is True
    stored = repr(
        await container.resolve(BaseLotRepository).list(
            Channel.SANDBOX,
        )
    ) + repr(await container.resolve(BaseSandboxRepository).offers())
    logs = '\n'.join(r.getMessage() for r in caplog.records)
    for secret in ('Secret-Pass-1', 'acc_login_2', 'Mail-Pass'):
        assert secret not in stored
        assert secret not in logs


def test_accounts_api_validation(auth_client):
    resp = auth_client.post(
        '/api/lots/sandbox/nope/accounts',
        json={'accounts': [{'login': 'a', 'password': 'b'}]},
    )
    assert resp.status_code == 404
    resp = auth_client.post(
        '/api/lots/sandbox/nope/accounts',
        json={'accounts': [{'login': '', 'password': 'b'}]},
    )
    assert resp.status_code == 422


# --- бот с типами ----------------------------------------------------------


async def _answer(bot_service, sandbox, chat_id):
    for chat in await sandbox.fetch_new_messages():
        await bot_service.store_incoming(chat, Channel.SANDBOX)
    return await bot_service.answer(sandbox, chat_id)


async def test_login_problem_goes_to_owner_without_llm(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
):
    s = await settings_service.get()
    s.telegram.notify_sandbox = True
    await settings_service.save(s)
    service = await _sandbox_lots(container)
    integrations.model.steps = [LLMReply('{"type_id": "dota_account"}')]
    await service.sync(Channel.SANDBOX)
    integrations.model.requests.clear()
    chats = container.resolve(SandboxService)
    chat = await chats.create_chat('buyer_acc')
    await chats.create_order(chat.chat_id, 'lot2', '', 0)
    await chats.say(chat.chat_id, 'Не могу войти, пароль не подходит')

    trace = await _answer(bot_service, sandbox, chat.chat_id)

    assert trace.outcome == 'handoff'
    assert integrations.model.requests == []  # ИИ не вызывался
    conv = await sandbox.chats.get_conversation(Channel.SANDBOX, chat.chat_id)
    assert conv.needs_human is True
    assert 'Аккаунт Dota 2' in conv.human_reason
    msgs = await sandbox.chats.messages(Channel.SANDBOX, chat.chat_id, 5)
    assert msgs[-1].text.startswith('Передал ваш вопрос продавцу')
    assert integrations.owner_notifier.sent[-1].startswith('[песочница] 🙋')


async def test_delivery_tool_uses_lot_type_and_queue(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service = await _sandbox_lots(container)
    await service.sync(Channel.SANDBOX)  # lot1 — подарок по ключу
    chats = container.resolve(SandboxService)
    chat = await chats.create_chat('gift_buyer')
    o = await chats.create_order(chat.chat_id, 'lot1', '', 0)
    await chats.set_friendship(
        chat.chat_id, 'friend', datetime.now(timezone.utc) - timedelta(days=10)
    )
    await chats.say(chat.chat_id, PROFILE)
    integrations.model.steps = [
        LLMReply(
            '',
            [
                ToolCall(
                    '1',
                    'save_steam_link',
                    {'order_id': o.order_id, 'link': PROFILE},
                )
            ],
        ),
        LLMReply('Сохранил'),
    ]
    await _answer(bot_service, sandbox, chat.chat_id)

    await chats.say(chat.chat_id, 'когда получу?')
    integrations.model.steps = [
        LLMReply(
            '', [ToolCall('1', 'get_delivery_info', {'order_id': o.order_id})]
        ),
        LLMReply('Примерно через 20 дней.'),
    ]
    trace = await _answer(bot_service, sandbox, chat.chat_id)
    info = trace.tool_calls[0].result
    assert info['product_type'] == 'Предмет Dota 2 подарком'
    assert info['days_left'] == 20
    assert info['queue']['days_until_send'] == 20
    assert info['queue']['gifts_per_day'] == 8
    prompt = integrations.model.requests[-2]
    assert any(
        'PRODUCT TYPES' in m['content']
        for m in prompt
        if m['role'] == 'system'
    )


async def test_link_rules_by_type(
    container, bot_service, sandbox, integrations
):
    service = await _sandbox_lots(container)
    integrations.model.steps = [LLMReply('{"type_id": "dota_account"}')]
    await service.sync(Channel.SANDBOX)
    chats = container.resolve(SandboxService)
    chat = await chats.create_chat('mix')
    trade = await chats.create_order(chat.chat_id, 'lot3', '', 0)
    account = await chats.create_order(chat.chat_id, 'lot2', '', 0)
    await chats.say(chat.chat_id, 'ссылки')
    integrations.model.steps = [
        LLMReply(
            '',
            [
                ToolCall(
                    '1',
                    'save_steam_link',
                    {'order_id': trade.order_id, 'link': PROFILE},
                ),
                ToolCall(
                    '2',
                    'save_steam_link',
                    {'order_id': account.order_id, 'link': PROFILE},
                ),
            ],
        ),
        LLMReply('ok'),
    ]
    trace = await _answer(bot_service, sandbox, chat.chat_id)
    assert 'trade offer link' in trace.tool_calls[0].result['error']
    assert 'no Steam link is needed' in trace.tool_calls[1].result['error']
