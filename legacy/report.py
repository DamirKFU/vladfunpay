"""HTML-отчёт по продажам FunPay из JSONL-выгрузки.

    python report.py --input sales.jsonl --out report.html

Отчёт — один самодостаточный HTML-файл (без внешних библиотек), данные
встроены в него. В нём имена покупателей, поэтому файл не стоит публиковать.
Ссылки на трейд Steam (type_data.player) в отчёт не попадают.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from models import MSK, ParseError, iter_records, to_decimal, to_msk_datetime

log = logging.getLogger("funpay.report")

TEMPLATE = Path(__file__).with_name("report_template.html")
DATA_MARKER = "/*__DATA__*/null"


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def _iso(value: Any) -> str | None:
    dt = to_msk_datetime(value)
    return dt.isoformat(timespec="seconds") if dt else None


def to_row(rec: dict[str, Any]) -> dict[str, Any]:
    """Компактная строка для отчёта: только нужные поля, даты в МСК."""
    review = rec.get("review") or {}
    amount = to_decimal(rec.get("amount"))
    return {
        "id": rec.get("order_uid"),
        "game": _get(rec, "game", "name") or "—",
        "cat": _get(rec, "type_data", "node", "name") or "—",
        "qty": _get(rec, "type_data", "amount"),
        "auto": bool(_get(rec, "type_data", "auto_delivery")),
        "price": float(amount) if amount is not None else 0.0,
        "cur": rec.get("currency") or "RUB",
        "status": rec.get("status") or "—",
        "created": _iso(rec.get("created_at")),
        "paid": _iso(rec.get("paid_at")),
        "closed": _iso(rec.get("closed_at")),
        "refunded": _iso(rec.get("refunded_at") or rec.get("partially_refunded_at")),
        "buyer_id": _get(rec, "buyer", "user_id"),
        "buyer": _get(rec, "buyer", "name") or "—",
        "rating": review.get("rating"),
        "review": review.get("text"),
        "reply": bool(review.get("reply")),
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for lineno, _, rec in iter_records(f, str(path)):
            try:
                row = to_row(rec)
            except ParseError as e:
                raise ParseError(f"{path}:{lineno}: {e}") from e
            rows[str(row["id"] or f"line-{lineno}")] = row  # дедупликация по номеру заказа
    return sorted(rows.values(), key=lambda r: r["paid"] or "")


def render(rows: list[dict[str, Any]], source: str) -> str:
    payload = {
        "generated": datetime.now(MSK).isoformat(timespec="seconds"),
        "source": source,
        "orders": rows,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = TEMPLATE.read_text(encoding="utf-8")
    if DATA_MARKER not in html:
        raise RuntimeError(f"в {TEMPLATE.name} нет метки {DATA_MARKER}")
    return html.replace(DATA_MARKER, data)


def build_report(input_path: Path, out: Path) -> Path:
    rows = load_rows(input_path)
    out.write_text(render(rows, input_path.name), encoding="utf-8")
    log.info("Отчёт: %s (%d заказов)", out, len(rows))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="HTML-отчёт по продажам FunPay")
    p.add_argument("--input", type=Path, default=Path("sales.jsonl"), help="JSONL-выгрузка (default: sales.jsonl)")
    p.add_argument("--out", type=Path, default=Path("report.html"), help="куда сохранить (default: report.html)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        build_report(args.input, args.out)
    except (OSError, ParseError) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
