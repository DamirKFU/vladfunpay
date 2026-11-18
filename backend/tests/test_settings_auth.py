from app.models.app_settings import AppSettings, from_dict
from app.repositories.base import BaseSettingsRepository


async def test_secrets_are_encrypted_and_masked(container, settings_service):
    await settings_service.update(
        {
            'funpay': {'golden_key': 'gk-1234567890'},
            'friends': {'auto_cleanup': True},
        },
    )
    raw = await container.resolve(BaseSettingsRepository).load()
    assert raw['funpay']['golden_key'] not in ('', 'gk-1234567890')

    public = await settings_service.public()
    assert public['funpay']['golden_key'] == {'is_set': True, 'hint': '…7890'}
    assert 'auto_cleanup' not in public['friends']
    assert (await settings_service.get()).funpay.golden_key == 'gk-1234567890'


async def test_secret_update_rules(settings_service):
    await settings_service.update({'steam': {'api_key': 'KEY123456789'}})
    # Пустая строка из формы ключ не стирает.
    await settings_service.update({'steam': {'api_key': '', 'steam_id': '1'}})
    s = await settings_service.get()
    assert s.steam.api_key == 'KEY123456789'
    assert s.steam.steam_id == '1'
    # None — явное удаление.
    await settings_service.update({'steam': {'api_key': None}})
    assert (await settings_service.get()).steam.api_key == ''


def test_old_settings_get_new_defaults():
    s = from_dict(AppSettings, {'bot': {'enabled': True}})
    assert not hasattr(s, 'bot')
    assert s.friends.refresh_hours == 3


def test_setup_login_and_protection(client):
    assert client.get('/api/auth/state').json() == {'needs_setup': True}
    assert client.get('/api/settings').status_code == 401

    creds = {'username': 'admin', 'password': 'password123'}
    assert client.post('/api/auth/setup', json=creds).status_code == 201
    assert client.post('/api/auth/setup', json=creds).status_code == 409

    bad = client.post(
        '/api/auth/login',
        json={**creds, 'password': 'wrong-password'},
    )
    assert bad.status_code == 401
    token = client.post('/api/auth/login', json=creds).json()['token']
    resp = client.get(
        '/api/settings',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert resp.status_code == 200
    assert resp.json()['funpay']['golden_key'] == {'is_set': False, 'hint': ''}


def test_login_rate_limit(client):
    client.post(
        '/api/auth/setup',
        json={'username': 'admin', 'password': 'password123'},
    )
    wrong = {'username': 'admin', 'password': 'nope-nope'}
    codes = [
        client.post('/api/auth/login', json=wrong).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


def test_users_crud_keeps_last_user(auth_client):
    resp = auth_client.post(
        '/api/users',
        json={'username': 'friend', 'password': 'short'},
    )
    assert resp.status_code == 422
    resp = auth_client.post(
        '/api/users',
        json={'username': 'friend', 'password': 'longpassword'},
    )
    assert resp.status_code == 201
    names = [u['username'] for u in auth_client.get('/api/users').json()]
    assert names == ['admin', 'friend']
    assert 'password_hash' not in auth_client.get('/api/users').text
    assert auth_client.delete('/api/users/friend').status_code == 200
    assert auth_client.delete('/api/users/admin').status_code == 409


def test_settings_patch_via_api_never_returns_secret(auth_client):
    resp = auth_client.patch(
        '/api/settings',
        json={
            'steam': {'api_key': 'AQVN-secret-key'},
            'funpay': {'auto_raise': True},
        },
    )
    assert resp.status_code == 200
    assert 'AQVN-secret-key' not in resp.text
    assert resp.json()['funpay']['auto_raise'] is True
