import io
import json
import zipfile
from datetime import date, datetime, timezone

import requests

from app.integrations.funpay.exports import (
    extract_new_id,
    parse_app_data,
    parse_export_payload,
    parse_exports_table,
)
from app.integrations.funpay.orders import order_from_export
from app.models.domain import SyncStatus
from app.repositories.base import BaseOrderRepository
from app.usecases.sync import SyncService, sync_window


def test_order_from_real_export_format(export_records):
    order = order_from_export(export_records[0])
    assert order.order_uid == 'ABCD1234'
    assert order.amount == 749.0
    assert order.category == 'Предметы'
    assert order.node_id == 210
    assert order.paid_at == datetime(
        2024, 7, 10, 13, 22, 58, tzinfo=timezone.utc
    )
    assert order.steam_id == str(76561197960265728 + 889002523)


def test_sync_window():
    today = date(2026, 11, 17)
    assert sync_window(today, None, None) == (None, today)
    last = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert sync_window(today, last, None) == (date(2026, 11, 9), today)
    old_open = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    assert sync_window(today, last, old_open) == (date(2026, 9, 30), today)


async def test_first_sync_is_all_time_then_incremental(
    container,
    integrations,
    export_records,
):
    integrations.order_exporter.records = export_records
    service = container.resolve(SyncService)

    first = await service.run_now()
    assert first.status == SyncStatus.DONE
    assert first.date_from is None
    assert first.fetched == 3

    second = await service.run_now()
    # Самый старый незакрытый заказ оплачен 2025-11-01 — с него и берём.
    assert second.date_from == '2025-10-31'
    assert second.fetched == 1

    orders = container.resolve(BaseOrderRepository)
    assert await orders.count() == 3
    history = await service.history()
    assert [r.id for r in history] == [second.id, first.id]


async def test_sync_error_is_recorded(container, integrations):
    class Broken(type(integrations.order_exporter)):
        async def export(self, date_from, date_to):
            from app.integrations.funpay.base import MarketplaceAuthError

            raise MarketplaceAuthError('golden_key устарел')

    integrations.order_exporter = Broken()
    run = await container.resolve(SyncService).run_now()
    assert run.status == SyncStatus.ERROR
    assert 'golden_key' in run.message


def test_parse_export_payload_zip_and_empty():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('funpay_sales_x.jsonl', '{"a": 1}\n{"a": 2}\n')
    assert parse_export_payload(buf.getvalue()) == [{'a': 1}, {'a': 2}]
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, 'w') as zf:
        zf.writestr('funpay_sales_x.jsonl', '')
    assert parse_export_payload(empty.getvalue()) == []


def test_extract_new_id_from_real_json_answer():
    resp = requests.Response()
    resp.url = 'https://funpay.com/exports/create'
    resp.status_code = 200
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    resp._content = json.dumps(
        {'url': 'https://funpay.com/exports/?new=IoLojJU7BcHaTlmT'},
    ).encode()
    assert extract_new_id(resp) == 'IoLojJU7BcHaTlmT'


def test_parse_exports_table_from_real_row():
    html = """<table class="js-exports-table"><tr data-export-id="AfZO">
    <td class="exports-table-status"><a class="js-export-download"
    href="https://funpay.com/exports/download?id=AfZO">Скачать</a></td>
    </tr><tr data-export-id="B"><td>Файл удалён</td></tr></table>"""
    rows = parse_exports_table(html)
    assert rows['AfZO']['url'].endswith('id=AfZO')
    assert rows['B'] == {'url': None, 'deleted': True}


def test_parse_app_data():
    html = (
        '<body data-app-data=\'{"csrf-token": "tok", '
        '"userId": 11294532}\'></body>'
    )
    assert parse_app_data(html) == ('tok', 11294532)


def test_sync_api_and_report(auth_client, integrations, export_records):
    integrations.order_exporter.records = export_records
    run = auth_client.post('/api/sync').json()
    assert run['status'] in ('running', 'done')
    summary = auth_client.get('/api/orders/summary').json()
    assert summary['count'] == 3
    report = auth_client.get('/api/orders/report').text
    assert 'Продажи FunPay' in report
    assert 'SECRETTOKEN' not in report
