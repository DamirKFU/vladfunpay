"""Отчёт: строка по реальной схеме выгрузки (значения выдуманы)."""
import json

from report import load_rows, render, to_row

REC = {
    "order_uid": "ABCD1234", "game": {"game_id": 41, "name": "Dota 2"},
    "section": {"type_id": "lot", "local_id": 210},
    "buyer": {"user_id": 1, "name": "buyer_x"}, "seller": {"user_id": 2, "name": "me"},
    "currency": "RUB", "amount": "749.00",
    "created_at": "2024-07-10T13:22:28Z", "paid_at": "2024-07-10T13:22:58Z",
    "closed_at": "2024-08-10T12:46:12Z", "refunded_at": None, "partially_refunded_at": None,
    "status": "closed", "role": "seller", "chat": {"node_name": "users-1-2"},
    "review": {"text": "</script><b>ok", "rating": 5, "reply": None, "hidden": False},
    "type_data": {"node": {"node_id": 210, "name": "Предметы"}, "amount": "1",
                  "player": "https://steamcommunity.com/tradeoffer/new/?partner=1&token=SECRET",
                  "auto_delivery": False, "server": None, "side": None},
}


def test_to_row_fields_and_msk():
    r = to_row(REC)
    assert r["id"] == "ABCD1234" and r["game"] == "Dota 2" and r["cat"] == "Предметы"
    assert r["price"] == 749.0 and r["rating"] == 5
    assert r["paid"] == "2024-07-10T16:22:58+03:00"


def test_report_hides_trade_link_and_escapes_script(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps(REC) + "\n" + json.dumps(REC) + "\n", encoding="utf-8")
    rows = load_rows(p)
    assert len(rows) == 1  # дедупликация по order_uid
    html = render(rows, "s.jsonl")
    assert "SECRET" not in html and "steamcommunity" not in html
    assert "</script><b>" not in html
