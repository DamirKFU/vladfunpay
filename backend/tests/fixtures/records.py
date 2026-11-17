"""Записи в формате реальной выгрузки FunPay orders_seller.

Ключи взяты из настоящей выгрузки, значения выдуманы, покупатели
замаскированы.
"""

import copy

import pytest

BASE_RECORD = {
    'order_uid': 'ABCD1234',
    'game': {'game_id': 41, 'name': 'Dota 2'},
    'section': {'type_id': 'lot', 'local_id': 210},
    'buyer': {'user_id': 1001, 'name': 'buyer_one'},
    'seller': {'user_id': 2, 'name': 'seller'},
    'currency': 'RUB',
    'amount': '749.00',
    'created_at': '2024-07-10T13:22:28Z',
    'paid_at': '2024-07-10T13:22:58Z',
    'closed_at': '2024-08-10T12:46:12Z',
    'refunded_at': None,
    'partially_refunded_at': None,
    'status': 'closed',
    'role': 'seller',
    'chat': {'node_name': 'users-1001-2'},
    'review': {
        'text': 'Отличный продавец',
        'rating': 5,
        'reply': None,
        'hidden': False,
    },
    'type_data': {
        'node': {'node_id': 210, 'name': 'Предметы'},
        'amount': '1',
        'player': 'https://steamcommunity.com/tradeoffer/new/'
        '?partner=889002523&token=SECRETTOKEN',
        'auto_delivery': False,
        'server': None,
        'side': None,
    },
}


def make_record(**changes) -> dict:
    record = copy.deepcopy(BASE_RECORD)
    for key, value in changes.items():
        record[key] = value
    return record


@pytest.fixture
def export_records() -> list[dict]:
    return [
        make_record(),
        make_record(
            order_uid='EFGH5678',
            status='refunded',
            amount='450.00',
            paid_at='2024-07-11T18:18:46Z',
            refunded_at='2024-07-17T17:11:55Z',
            buyer={'user_id': 1002, 'name': 'buyer_two'},
        ),
        make_record(
            order_uid='OPEN0001',
            status='paid',
            amount='1300.00',
            paid_at='2025-11-01T10:00:00Z',
            closed_at=None,
            review=None,
            buyer={'user_id': 1003, 'name': 'buyer_three'},
        ),
    ]
