"""Конвейер бота на песочнице и модели с заранее заданными ответами."""

from datetime import datetime, timedelta, timezone

from app.bot.debounce import ChatDebouncer
from app.integrations.llm.base import LLMReply, ToolCall
from app.models.app_settings import ReplyTemplate
from app.models.domain import Channel, Offer, OpenOrder
from app.repositories.base import (
    BaseSandboxRepository,
    BaseSteamLinkRepository,
)
from app.usecases.chats import SandboxService
from app.workers.bot_worker import BotWorker


async def _chat_with_order(container, sandbox_service=None):
    service = sandbox_service or container.resolve(SandboxService)
    conv = await service.create_chat('buyer_x')
    await container.resolve(BaseSandboxRepository).save_offer(
        Offer(offer_id='lot1', title='Arcana Pudge', price=749, amount=3),
    )
    order = await service.create_order(conv.chat_id, 'lot1', '', 0)
    return service, conv, order


async def _answer(bot_service, sandbox, chat_id):
    for chat in await sandbox.fetch_new_messages():
        await bot_service.store_incoming(chat, Channel.SANDBOX)
    return await bot_service.answer(sandbox, chat_id)


async def test_reply_uses_tools_and_sends_russian_text(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, order = await _chat_with_order(container)
    await service.say(conv.chat_id, 'где мой заказ?')
    integrations.model.steps = [
        LLMReply('', [ToolCall('1', 'get_open_orders', {})], tokens=50),
        LLMReply(f'Заказ #{order.order_id} в работе.', tokens=30),
    ]

    trace = await _answer(bot_service, sandbox, conv.chat_id)

    assert trace.outcome == 'replied'
    assert trace.tokens == 80
    assert trace.tool_calls[0].result[0]['order_id'] == order.order_id
    tool_message = integrations.model.requests[1][-1]
    assert tool_message['role'] == 'tool'
    msgs = await sandbox.chats.messages(Channel.SANDBOX, conv.chat_id, 10)
    assert msgs[-1].text == f'Заказ #{order.order_id} в работе.'


async def test_assortment_tool_reports_stock(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, _ = await _chat_with_order(container)
    await service.say(conv.chat_id, 'есть ещё arcana?')
    integrations.model.steps = [
        LLMReply('', [ToolCall('1', 'get_assortment', {'query': 'arcana'})]),
        LLMReply('Да, осталось 2.'),
    ]
    trace = await _answer(bot_service, sandbox, conv.chat_id)
    # Один лот куплен при создании заказа: было 3, осталось 2.
    assert trace.tool_calls[0].result == [
        {
            'title': 'Arcana Pudge',
            'price': 749,
            'in_stock': 2,
            'auto_delivery': False,
        },
    ]


async def test_save_steam_link_validates_in_code(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, order = await _chat_with_order(container)
    await service.say(conv.chat_id, 'вот ссылка')
    good = 'https://steamcommunity.com/tradeoffer/new/?partner=123&token=abc'
    integrations.model.steps = [
        LLMReply(
            '',
            [
                ToolCall(
                    '1', 'save_steam_link', {'order_id': 'NOPE', 'link': good}
                ),
                ToolCall(
                    '2',
                    'save_steam_link',
                    {'order_id': order.order_id, 'link': 'not a link'},
                ),
                ToolCall(
                    '3',
                    'save_steam_link',
                    {'order_id': order.order_id, 'link': good},
                ),
            ],
        ),
        LLMReply('Ссылку сохранил.'),
    ]
    trace = await _answer(bot_service, sandbox, conv.chat_id)

    results = [c.result for c in trace.tool_calls]
    assert 'error' in results[0]
    assert 'error' in results[1]
    assert results[2]['steam_id'] == str(76561197960265728 + 123)
    links = await container.resolve(BaseSteamLinkRepository).list(
        Channel.SANDBOX,
    )
    assert links[0].order_id == order.order_id


async def test_request_human_stops_bot_until_resumed(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, _ = await _chat_with_order(container)
    await service.say(conv.chat_id, 'верните деньги!!!')
    integrations.model.steps = [
        LLMReply('', [ToolCall('1', 'request_human', {'reason': 'refund'})]),
        LLMReply('Передал продавцу, он скоро ответит.'),
    ]
    await _answer(bot_service, sandbox, conv.chat_id)

    await service.say(conv.chat_id, 'ау')
    trace = await _answer(bot_service, sandbox, conv.chat_id)
    assert trace.outcome == 'skipped'
    assert trace.detail == 'чат передан продавцу'


async def test_template_answers_without_llm(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
):
    settings = await settings_service.get()
    settings.bot.templates = [
        ReplyTemplate(keywords=['гарантия'], reply='Гарантия 7 дней.'),
    ]
    await settings_service.save(settings)
    service, conv, _ = await _chat_with_order(container)
    await service.say(conv.chat_id, 'Какая ГАРАНТИЯ?')

    trace = await _answer(bot_service, sandbox, conv.chat_id)

    assert trace.outcome == 'template'
    assert integrations.model.requests == []


async def test_no_open_orders_means_no_llm(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service = container.resolve(SandboxService)
    conv = await service.create_chat('stranger')
    await service.say(conv.chat_id, 'привет')

    trace = await _answer(bot_service, sandbox, conv.chat_id)

    assert trace.detail == 'нет открытых заказов'
    assert integrations.model.requests == []


async def test_daily_token_limit(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
):
    settings = await settings_service.get()
    settings.bot.daily_token_limit = 100
    await settings_service.save(settings)
    service, conv, _ = await _chat_with_order(container)
    integrations.model.steps = [LLMReply('Ок', tokens=150)]
    await service.say(conv.chat_id, 'раз')
    assert (await _answer(bot_service, sandbox, conv.chat_id)).tokens == 150

    await service.say(conv.chat_id, 'два')
    trace = await _answer(bot_service, sandbox, conv.chat_id)
    assert trace.outcome == 'skipped'
    assert 'лимит токенов' in trace.detail


async def test_reply_is_discarded_when_buyer_writes_again(
    container,
    bot_service,
    sandbox,
    integrations,
):
    service, conv, _ = await _chat_with_order(container)
    await service.say(conv.chat_id, 'первое')

    async def buyer_writes_while_model_thinks(messages):
        await service.say(conv.chat_id, 'и ещё вопрос')
        return LLMReply('ответ только на первое')

    integrations.model.steps = [
        buyer_writes_while_model_thinks,
        LLMReply('ответ на оба'),
    ]
    trace = await _answer(bot_service, sandbox, conv.chat_id)
    assert trace.outcome == 'discarded'

    trace = await _answer(bot_service, sandbox, conv.chat_id)
    assert trace.outcome == 'replied'
    assert trace.input_text == 'первое\nи ещё вопрос'
    msgs = await sandbox.chats.messages(Channel.SANDBOX, conv.chat_id, 10)
    assert [m.text for m in msgs if m.author == 'bot'] == ['ответ на оба']


def test_debouncer_waits_for_silence_with_ceiling():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    d = ChatDebouncer()
    d.touch('c', t0)
    d.touch('c', t0 + timedelta(seconds=4))
    assert d.due(t0 + timedelta(seconds=8), 7, 40) == []
    assert d.due(t0 + timedelta(seconds=11), 7, 40) == ['c']

    d.touch('c', t0)
    for s in range(0, 45, 3):  # покупатель пишет без пауз
        d.touch('c', t0 + timedelta(seconds=s))
    assert d.due(t0 + timedelta(seconds=40), 7, 40) == ['c']


async def test_worker_end_to_end_on_sandbox(
    container,
    bot_service,
    sandbox,
    integrations,
    settings_service,
):
    settings = await settings_service.get()
    settings.bot.reply_delay_sec = 0
    settings.bot.poll_interval_sec = 0
    await settings_service.save(settings)
    service, conv, _ = await _chat_with_order(container)
    integrations.model.steps = [LLMReply('Здравствуйте!')]

    async def make(_):
        return sandbox

    worker = BotWorker('test', bot_service, make)
    await service.say(conv.chat_id, 'добрый день')
    await worker.tick()

    msgs = await sandbox.chats.messages(Channel.SANDBOX, conv.chat_id, 10)
    assert [m.author for m in msgs] == ['buyer', 'bot']
    assert worker.state.last_error == ''


async def test_closed_sandbox_order_is_not_open(container, sandbox):
    service, conv, order = await _chat_with_order(container)
    await service.set_order_status(order.order_id, 'closed')
    assert await sandbox.open_orders(conv.buyer_id) == []
    assert isinstance((await service.orders(conv.chat_id))[0], OpenOrder)
