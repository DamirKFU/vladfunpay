"""Модель заказа и потоковый разбор JSONL-выгрузки.

Схема JSONL пока неизвестна, поэтому ключи не зашиты в код: соответствие
задаётся в FIELD_MAP. Заполните его по выводу `python main.py inspect`.
Всё, что не попало в FIELD_MAP, сохраняется в Order.extra.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class FieldMap:
    """Какой ключ JSONL соответствует какому полю модели (None = нет/неизвестно).

    Вложенные ключи пишутся через точку ("game.name"): значение берётся,
    а исходный объект остаётся в extra целиком.
    """

    order_id: str | None = None
    status: str | None = None
    amount: str | None = None
    game: str | None = None
    # Ключи с датами: приводятся к datetime в Europe/Moscow.
    date_fields: tuple[str, ...] = ()
    # Прочие денежные ключи: приводятся к Decimal.
    decimal_fields: tuple[str, ...] = ()


# Ключи проверены по реальной выгрузке orders_seller (JSONL).
FIELD_MAP = FieldMap(
    order_id="order_uid",
    status="status",  # closed / refunded / paid
    amount="amount",
    game="game.name",
    date_fields=("created_at", "paid_at", "closed_at", "refunded_at", "partially_refunded_at"),
)


@dataclass
class Order:
    order_id: str | None
    status: str | None
    amount: Decimal | None
    game: str | None
    dates: dict[str, datetime | None] = field(default_factory=dict)
    decimals: dict[str, Decimal | None] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    raw_line: str = ""

    @property
    def dedup_key(self) -> str:
        """Номер заказа; пока он не задан в FIELD_MAP, хэш исходной строки."""
        if self.order_id:
            return self.order_id
        return "sha1:" + hashlib.sha1(self.raw_line.encode()).hexdigest()


class ParseError(ValueError):
    pass


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ParseError(f"ожидалось число, получено {value!r}")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).replace(" ", "").replace(" ", "").replace("₽", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as e:
        raise ParseError(f"не число: {value!r}") from e


def to_msk_datetime(value: Any) -> datetime | None:
    """ISO-строка, 'YYYY-MM-DD HH:MM:SS' или unix-время -> aware datetime (МСК).

    Время без пояса считается московским.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(MSK)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).astimezone(MSK)
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue
    else:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ParseError(f"неизвестный формат даты: {value!r}")
    return dt.replace(tzinfo=MSK) if dt.tzinfo is None else dt.astimezone(MSK)


def parse_record(record: dict[str, Any], fmap: FieldMap = FIELD_MAP, raw_line: str = "") -> Order:
    rest = dict(record)

    def take(key: str | None) -> Any:
        if not key:
            return None
        if "." not in key:
            return rest.pop(key, None)
        value: Any = record
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    order_id = take(fmap.order_id)
    status = take(fmap.status)
    amount = take(fmap.amount)
    game = take(fmap.game)
    dates = {k: to_msk_datetime(rest.pop(k)) for k in fmap.date_fields if k in rest}
    decimals = {k: to_decimal(rest.pop(k)) for k in fmap.decimal_fields if k in rest}
    return Order(
        order_id=None if order_id is None else str(order_id).lstrip("#"),
        status=None if status is None else str(status),
        amount=to_decimal(amount),
        game=None if game is None else str(game),
        dates=dates,
        decimals=decimals,
        extra=rest,
        raw_line=raw_line,
    )


def iter_records(lines: Iterable[str], source: str = "") -> Iterator[tuple[int, str, dict[str, Any]]]:
    """(номер строки, исходная строка, dict). Пустые строки пропускаются."""
    where = f"{source}:" if source else "строка "
    for lineno, line in enumerate(lines, 1):
        line = line.strip().lstrip("﻿")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ParseError(f"{where}{lineno}: невалидный JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ParseError(f"{where}{lineno}: ожидался объект, получено {type(obj).__name__}")
        yield lineno, line, obj


def iter_orders(path: Path, fmap: FieldMap = FIELD_MAP) -> Iterator[Order]:
    """Потоковый разбор файла: в памяти одна строка за раз."""
    with path.open(encoding="utf-8") as f:
        for lineno, line, obj in iter_records(f, str(path)):
            try:
                yield parse_record(obj, fmap, raw_line=line)
            except ParseError as e:
                raise ParseError(f"{path}:{lineno}: {e}") from e
