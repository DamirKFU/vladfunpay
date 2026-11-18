"""Журнал действий и автоподнятие."""

import logging
from datetime import datetime, timedelta, timezone

from app.integrations.funpay.base import RaiseResult
from app.integrations.funpay.orders import order_from_export
from app.integrations.steam.web import access_token, explain_status
from app.repositories.base import BaseOrderRepository
from app.usecases.raise_lots import RaiseService

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def test_api_requests_and_errors_are_logged(auth_client, caplog):
    caplog.set_level(logging.INFO)
    auth_client.patch(
        '/api/settings',
        json={
            'funpay': {'golden_key': 'gk-very-secret-1'},
            'friends': {'refresh_hours': 15},
        },
    )
    auth_client.post(
        '/api/users',
        json={'username': 'friend', 'password': 'short'},
    )
    auth_client.get('/api/journal/orders')  # опрос — в лог не пишется

    text = '\n'.join(r.getMessage() for r in caplog.records)
    assert 'API PATCH /api/settings → 200' in text
    assert (
        'Настройки изменены: friends.refresh_hours, funpay.golden_key' in text
    )
    assert 'gk-very-secret-1' not in text
    assert 'POST /api/users: пароль должен быть не короче 8' in text
    assert 'API POST /api/users → 422' in text
    assert '/api/journal/orders' not in text


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


def test_raise_api(auth_client):
    assert auth_client.get('/api/funpay/raise').json() == {
        'enabled': False,
        'categories': [],
    }
