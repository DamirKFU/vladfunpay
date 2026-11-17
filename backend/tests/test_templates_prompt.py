"""Шаблоны по фразам и редактируемый промпт."""

from app.bot.prompt import DEFAULT_STYLE, TOOL_RULES, compose_system_prompt
from app.bot.templates import find_template, render_reply, similarity
from app.models.app_settings import BotSettings, ReplyExample, ReplyTemplate


def test_phrase_templates():
    bot = BotSettings(
        templates=[
            ReplyTemplate(
                examples=['Когда я получу предмет?'],
                reply='{buyer}, подарки приходят через 30 дней дружбы.',
            ),
            ReplyTemplate(keywords=['гарантия'], reply='Гарантия 7 дней.'),
        ],
    )
    assert (
        similarity('когда получу свой предмет', 'когда я получу предмет')
        >= 0.8
    )
    match = find_template(bot, 'Здравствуйте! Когда получу предмет??')
    assert match and match.score >= 0.6
    assert render_reply(match.template, 'Petya').startswith('Petya,')
    assert find_template(bot, 'а какая гарантия').reason == 'слово «гарантия»'
    assert find_template(bot, 'сколько стоит аркана на пуджа') is None


def test_prompt_keeps_tool_rules_and_uses_custom_style():
    default = compose_system_prompt(BotSettings())
    assert TOOL_RULES in default and DEFAULT_STYLE in default

    custom = compose_system_prompt(
        BotSettings(
            style_prompt='Общайся на «вы», без смайликов.',
            examples=[ReplyExample('скинь дешевле', 'Цена фиксированная.')],
        ),
    )
    assert TOOL_RULES in custom
    assert DEFAULT_STYLE not in custom
    assert 'Общайся на «вы»' in custom
    assert 'Buyer: скинь дешевле\nYou: Цена фиксированная.' in custom


def test_prompt_and_friendship_api(auth_client):
    auth_client.patch(
        '/api/settings',
        json={'bot': {'style_prompt': 'Пиши коротко.'}},
    )
    prompt = auth_client.get('/api/bot/prompt').json()
    assert 'Пиши коротко.' in prompt['composed']
    assert prompt['tool_rules'] in prompt['composed']

    chat = auth_client.post('/api/sandbox/chats', json={}).json()
    url = f'/api/sandbox/chats/{chat["chat_id"]}/friendship'
    resp = auth_client.put(url, json={'relationship': 'friend'})
    assert resp.json()['relationship'] == 'friend'
    assert resp.json()['since'] is not None
    resp = auth_client.put(url, json={'relationship': 'invite_sent'})
    assert resp.json() == {'relationship': 'invite_sent', 'since': None}
