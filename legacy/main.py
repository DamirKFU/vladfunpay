"""Выгрузка продаж FunPay в JSONL.

Примеры:
    python main.py --inspect --debug          # 7 дней: 3 строки + список ключей
    python main.py --from 2025-01-01 --to 2025-12-31 --out sales.jsonl
    python main.py --input sales.jsonl        # только итоги по готовому файлу
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from auth import AuthError, BlockedError, SecretsFilter, build_session, load_credentials
from client import ExportError, FunPayClient
from models import FIELD_MAP, MSK, FieldMap, Order, ParseError, iter_orders, iter_records

log = logging.getLogger("funpay")

EXPORT_LIMIT = 100_000


# --- окна дат ---------------------------------------------------------------


def split_range(start: date, end: date, days: int) -> Iterator[tuple[date, date]]:
    """Делит [start, end] (включительно) на окна не длиннее days дней."""
    if days < 1:
        raise ValueError("split_days должен быть >= 1")
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=days - 1), end)
        yield cur, win_end
        cur = win_end + timedelta(days=1)


# --- объединение и итоги ----------------------------------------------------


@dataclass
class Summary:
    total: int = 0
    duplicates: int = 0
    by_status: dict[str, list[Any]] = field(default_factory=lambda: defaultdict(lambda: [0, Decimal(0)]))
    games: Counter[str] = field(default_factory=Counter)
    game_amounts: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))

    def add(self, order: Order) -> None:
        self.total += 1
        status = order.status or "—"
        self.by_status[status][0] += 1
        self.by_status[status][1] += order.amount or Decimal(0)
        if order.game:
            self.games[order.game] += 1
            self.game_amounts[order.game] += order.amount or Decimal(0)

    def render(self, fmap: FieldMap, top: int = 10) -> str:
        lines = [f"Заказов: {self.total} (дубликатов отброшено: {self.duplicates})"]
        if fmap.status is None or fmap.amount is None or fmap.game is None:
            lines.append("! FIELD_MAP в models.py не заполнен: итоги по статусам/играм неполные.")
        lines.append("По статусам (кол-во / сумма):")
        for status, (count, amount) in sorted(self.by_status.items(), key=lambda kv: -kv[1][0]):
            lines.append(f"  {status:<20} {count:>7}  {amount:>14,.2f}")
        if self.games:
            lines.append(f"Топ-{top} игр (кол-во / сумма):")
            for game, count in self.games.most_common(top):
                lines.append(f"  {game:<30} {count:>7}  {self.game_amounts[game]:>14,.2f}")
        return "\n".join(lines)


def merge_files(parts: list[Path], out: Path, fmap: FieldMap = FIELD_MAP) -> Summary:
    """Объединяет файлы окон в out с дедупликацией по номеру заказа.

    Читает построчно; в памяти держится только множество ключей.
    Строки пишутся в исходном виде, чтобы не потерять ни одного поля.
    """
    summary = Summary()
    seen: set[str] = set()
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for part in parts:
            for order in iter_orders(part, fmap):
                key = order.dedup_key
                if key in seen:
                    summary.duplicates += 1
                    continue
                seen.add(key)
                f.write(order.raw_line + "\n")
                summary.add(order)
    tmp.replace(out)
    return summary


def summarize_file(path: Path, fmap: FieldMap = FIELD_MAP) -> Summary:
    summary = Summary()
    seen: set[str] = set()
    for order in iter_orders(path, fmap):
        if order.dedup_key in seen:
            summary.duplicates += 1
            continue
        seen.add(order.dedup_key)
        summary.add(order)
    return summary


def inspect_file(path: Path, sample: int = 3) -> str:
    """Первые строки и все встречающиеся ключи с типами значений и частотой."""
    keys: dict[str, Counter[str]] = defaultdict(Counter)
    first: list[str] = []
    total = 0
    with path.open(encoding="utf-8") as f:
        for _, line, obj in iter_records(f):
            total += 1
            if len(first) < sample:
                first.append(line)
            for k, v in obj.items():
                keys[k][type(v).__name__] += 1
    out = [f"Файл {path}: {total} строк", f"Первые {len(first)} строки:"]
    out += [f"  {line}" for line in first]
    out.append("Ключи (в скольких строках / типы):")
    for k, types in keys.items():
        out.append(f"  {k:<30} {sum(types.values()):>7}  {dict(types)}")
    return "\n".join(out)


# --- CLI ----------------------------------------------------------------------


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"ожидалась дата YYYY-MM-DD: {value!r}") from e


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Выгрузка продаж FunPay в JSONL")
    p.add_argument("--from", dest="date_from", type=parse_date, help="оплачено с (YYYY-MM-DD); не задано = за всё время")
    p.add_argument("--to", dest="date_to", type=parse_date, help="оплачено по (YYYY-MM-DD); по умолчанию сегодня (МСК)")
    p.add_argument("--out", type=Path, default=Path("sales.jsonl"), help="итоговый файл (default: sales.jsonl)")
    p.add_argument("--lot-fields", action="store_true", help="добавить поля лота (файл сильно больше)")
    p.add_argument("--split-days", type=int, default=None,
                   help="делить период на окна по N дней (только если заказов больше 100 000); "
                        "по умолчанию одна выгрузка")
    p.add_argument("--inspect", action="store_true", help="выгрузить последние 7 дней и показать 3 строки и ключи")
    p.add_argument("--input", type=Path, help="не скачивать, а посчитать итоги по готовому JSONL")
    p.add_argument("--poll-interval", type=float, default=20.0, help="интервал опроса /exports/, с (10–30)")
    p.add_argument("--poll-timeout", type=float, default=600.0, help="таймаут ожидания выгрузки, с")
    p.add_argument("--csrf-mode", choices=("body", "header", "both"), default="body",
                   help="как передавать CSRF-токен (проверить по Network)")
    p.add_argument("--keep-parts", action="store_true", help="не удалять файлы отдельных окон")
    p.add_argument("--html", type=Path, nargs="?", const=Path("report.html"),
                   help="после выгрузки собрать HTML-отчёт (default: report.html)")
    p.add_argument("--debug", action="store_true", help="отладочный вывод запросов (без секретов)")
    return p


def setup_logging(debug: bool) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretsFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    # urllib3 в DEBUG пишет заголовки запросов; держим его на INFO.
    logging.getLogger("urllib3").setLevel(logging.INFO)


def download_window(client: FunPayClient, d_from: date | None, d_to: date | None, dest: Path,
                    args: argparse.Namespace) -> Path:
    log.info("Окно %s — %s", d_from or "начало", d_to)
    export_id = client.create_export(d_from, d_to, lot_fields=args.lot_fields)
    url = client.wait_ready(export_id, interval=args.poll_interval, timeout=args.poll_timeout)
    client.download(url, dest)
    with dest.open(encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip())
    if count >= EXPORT_LIMIT:
        log.warning("За %s — %s %d заказов (лимит %d): часть могла не попасть, "
                    "повторите с --split-days (например, 90)",
                    d_from, d_to, count, EXPORT_LIMIT)
    return dest


def run(args: argparse.Namespace) -> int:
    if args.input:
        print(inspect_file(args.input) if args.inspect else summarize_file(args.input).render(FIELD_MAP))
        return 0

    today = datetime.now(MSK).date()
    d_to: date = args.date_to or today
    d_from: date | None = args.date_from
    if args.inspect and d_from is None:
        d_from = d_to - timedelta(days=7)
    if d_from and d_from > d_to:
        raise SystemExit("--from позже --to")

    creds = load_credentials()
    client = FunPayClient(build_session(creds), csrf_mode=args.csrf_mode, debug=args.debug or args.inspect)
    client.login()

    parts_dir = args.out.parent / f".{args.out.stem}_parts"
    parts: list[Path] = []
    windows: list[tuple[date | None, date]]
    if args.split_days is None:
        # Одна выгрузка на весь период, как кнопка «Выгрузить» на сайте.
        windows = [(d_from, d_to)]
    elif d_from is None:
        raise SystemExit("--split-days требует --from: период «за всё время» на окна не делится")
    else:
        windows = list(split_range(d_from, d_to, args.split_days))
        log.info("Период разбит на %d окон по %d дн.", len(windows), args.split_days)
    for i, (w_from, w_to) in enumerate(windows, 1):
        dest = parts_dir / f"{i:03d}_{w_from or 'all'}_{w_to}.jsonl"
        parts.append(download_window(client, w_from, w_to, dest, args))

    if args.inspect:
        print(inspect_file(parts[0]))
        if parts[0].stat().st_size == 0:
            print(f"\nЗа {d_from} — {d_to} продаж нет. Задайте период пошире: --inspect --from YYYY-MM-DD --to YYYY-MM-DD")
        print(f"\nФайл сохранён: {parts[0]}. Пришлите вывод выше (личные данные покупателей замаскируйте).")
        return 0

    summary = merge_files(parts, args.out)
    log.info("Сохранено %d заказов в %s", summary.total, args.out)
    if not args.keep_parts:
        shutil.rmtree(parts_dir, ignore_errors=True)
    print(summary.render(FIELD_MAP))
    if args.html:
        from report import build_report

        build_report(args.out, args.html)
        print(f"HTML-отчёт: {args.html}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.debug)
    try:
        return run(args)
    except AuthError as e:
        log.error("%s", e)
        return AuthError.exit_code
    except BlockedError as e:
        log.error("%s", e)
        return BlockedError.exit_code
    except (ExportError, ParseError) as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
