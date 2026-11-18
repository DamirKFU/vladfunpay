from app.models.domain import SalePreview


def test_read_only_orders_and_failed_refresh(auth_client, integrations):
    url = '/api/journal/orders'
    sync_url = f'{url}/funpay/sync'
    assert auth_client.get(url).json()['refreshed_at'] is None
    integrations.sales_reader.items = [
        SalePreview('OPEN', 'Item', 'buyer', 10, '₽', 'paid', 'сегодня'),
    ]
    response = auth_client.post(sync_url)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot['items'][0]['status'] == 'paid'
    assert snapshot['refreshed_at']

    integrations.sales_reader.fail = True
    assert auth_client.post(sync_url).status_code == 502
    stale = auth_client.get(url).json()
    assert stale['items'] == snapshot['items']
    assert stale['refreshed_at'] == snapshot['refreshed_at']
    assert stale['error']

    integrations.sales_reader.fail = False
    integrations.sales_reader.items = [
        SalePreview('OPEN', 'Item', 'buyer', 10, '₽', 'closed', 'сегодня'),
    ]
    updated = auth_client.post(sync_url).json()
    assert updated['items'][0]['status'] == 'closed'
    assert not updated['error']

    paths = auth_client.get('/api/openapi.json').json()['paths']
    assert set(paths[url]) == {'get'}
    assert set(paths[sync_url]) == {'post'}
    assert not any(
        path.startswith(
            (
                '/api/bot/',
                '/api/telegram/',
                '/api/lots/',
                '/api/sandbox/',
                '/api/appeals',
            )
        )
        for path in paths
    )
    assert (
        auth_client.put(f'{url}/funpay/OPEN/status', json={}).status_code
        == 404
    )
    assert (
        auth_client.post(f'{url}/funpay/OPEN/note', json={}).status_code == 404
    )
