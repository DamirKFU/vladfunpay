"""Разбор JSONL.

Ключи ниже СИНТЕТИЧЕСКИЕ (схема FunPay ещё не известна): тесты проверяют
механику через явный FieldMap и не зависят от реальных имён полей.
Тест на реальный образец включится, когда появится fixtures/real_sample.jsonl.
"""
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from main import inspect_file, merge_files, split_range
from models import FIELD_MAP, MSK, FieldMap, ParseError, iter_orders, parse_record, to_decimal, to_msk_datetime

FIXTURES = Path(__file__).parent / "fixtures"
TEST_MAP = FieldMap(order_id="k_id", status="k_status", amount="k_sum", game="k_game", date_fields=("k_paid",))


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def test_parse_record_maps_fields_and_keeps_extra():
    o = parse_record({"k_id": "#ABC123", "k_status": "x", "k_sum": "1 234,50", "k_game": "G",
                      "k_paid": "2025-03-01 12:00:00", "unknown": [1, 2]}, TEST_MAP)
    assert o.order_id == "ABC123"
    assert o.amount == Decimal("1234.50")
    assert o.dates["k_paid"] == datetime(2025, 3, 1, 12, 0, tzinfo=MSK)
    assert o.extra == {"unknown": [1, 2]}


def test_default_map_keeps_everything_in_extra():
    rec = {"a": 1, "b": "2"}
    o = parse_record(rec)
    assert o.extra == rec and o.order_id is None


@pytest.mark.parametrize("value, expected", [
    (10, Decimal(10)), (0.1, Decimal("0.1")), ("99.90 ₽", Decimal("99.90")), (None, None), ("", None),
])
def test_to_decimal(value, expected):
    assert to_decimal(value) == expected


def test_to_decimal_rejects_garbage():
    with pytest.raises(ParseError):
        to_decimal("abc")


def test_datetimes_are_moscow_aware():
    assert to_msk_datetime("2025-01-01T00:00:00Z") == datetime(2025, 1, 1, 3, 0, tzinfo=MSK)
    assert to_msk_datetime(0).utcoffset().total_seconds() == 3 * 3600
    assert to_msk_datetime("01.02.2025 10:30") == datetime(2025, 2, 1, 10, 30, tzinfo=MSK)


def test_iter_orders_streams_and_reports_bad_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"k_id": "1"}\n\nnot json\n', encoding="utf-8")
    it = iter_orders(p, TEST_MAP)
    assert next(it).order_id == "1"
    with pytest.raises(ParseError, match=r"x\.jsonl:3:"):
        next(it)


def test_merge_dedups_by_order_id(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"k_id": "1", "k_status": "paid", "k_sum": 10, "k_game": "G1"},
                                           {"k_id": "2", "k_status": "closed", "k_sum": 5, "k_game": "G2"}])
    b = write_jsonl(tmp_path / "b.jsonl", [{"k_id": "2", "k_status": "closed", "k_sum": 5, "k_game": "G2"},
                                           {"k_id": "3", "k_status": "paid", "k_sum": "2.5", "k_game": "G1"}])
    out = tmp_path / "out.jsonl"
    s = merge_files([a, b], out, TEST_MAP)
    assert s.total == 3 and s.duplicates == 1
    assert s.by_status["paid"] == [2, Decimal("12.5")]
    assert s.games.most_common(1) == [("G1", 2)]
    assert len(out.read_text(encoding="utf-8").splitlines()) == 3


def test_merge_without_field_map_dedups_identical_lines(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [{"x": 1}, {"x": 2}])
    b = write_jsonl(tmp_path / "b.jsonl", [{"x": 2}])
    assert merge_files([a, b], tmp_path / "o.jsonl", FieldMap()).total == 2


def test_inspect_lists_keys(tmp_path):
    p = write_jsonl(tmp_path / "a.jsonl", [{"a": 1}, {"a": None, "b": "s"}])
    text = inspect_file(p)
    assert "a " in text and "'NoneType': 1" in text and "b " in text


def test_split_range():
    from datetime import date
    w = list(split_range(date(2025, 1, 1), date(2025, 3, 31), 30))
    assert w[0] == (date(2025, 1, 1), date(2025, 1, 30))
    assert w[-1][1] == date(2025, 3, 31)
    assert all(b + __import__("datetime").timedelta(days=1) == c for (_, b), (c, _) in zip(w, w[1:]))


REAL = FIXTURES / "real_sample.jsonl"


@pytest.mark.skipif(not REAL.exists(), reason="нет fixtures/real_sample.jsonl (пришлите 2–3 строки)")
def test_real_sample_parses_with_field_map():
    orders = list(iter_orders(REAL, FIELD_MAP))
    assert orders
    if FIELD_MAP.order_id:
        assert all(o.order_id for o in orders)
    if FIELD_MAP.amount:
        assert all(isinstance(o.amount, Decimal) for o in orders)
