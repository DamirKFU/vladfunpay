"""Типы товаров: какой тип у лота и у заказа.

Порядок: ручной выбор владельца → слова-ключи типа в названии/описании →
ИИ по описанию карточки → тип по умолчанию. Заказ с FunPay несёт только
название, поэтому тип заказа берётся у лота с тем же названием.
"""

import json
import re
from typing import Any

from app.models.app_settings import CatalogSettings, ProductKind, ProductType
from app.models.domain import LotRecord

_SPACE_RE = re.compile(r'\s+')
_JSON_RE = re.compile(r'\{.*\}', re.S)
FALLBACK = ProductType(id='manual', name='Другое', kind=ProductKind.MANUAL)


def norm(text: str) -> str:
    return _SPACE_RE.sub(' ', text.lower().replace('ё', 'е')).strip()


def type_by_id(catalog: CatalogSettings, type_id: str) -> ProductType:
    by_id = {t.id: t for t in catalog.types}
    return (
        by_id.get(type_id)
        or by_id.get(catalog.default_type)
        or (catalog.types[0] if catalog.types else FALLBACK)
    )


def match_keywords(
    catalog: CatalogSettings,
    *texts: str,
) -> ProductType | None:
    haystack = norm(' '.join(texts))
    for ptype in catalog.types:
        words = [norm(k) for k in ptype.keywords if k.strip()]
        if any(w and w in haystack for w in words):
            return ptype
    return None


def find_lot(title: str, lots: list[LotRecord]) -> LotRecord | None:
    """Лот по названию заказа: точное совпадение, затем вхождение."""
    target = norm(title)
    if not target:
        return None
    for lot in lots:
        if norm(lot.title) == target:
            return lot
    candidates = [
        lot
        for lot in lots
        if lot.title.strip()
        and (norm(lot.title) in target or target in norm(lot.title))
    ]
    return max(candidates, key=lambda lot: len(lot.title), default=None)


def order_type(
    catalog: CatalogSettings,
    title: str,
    lots: list[LotRecord],
) -> ProductType:
    lot = find_lot(title, lots)
    if lot and lot.type_id:
        return type_by_id(catalog, lot.type_id)
    return match_keywords(catalog, title) or type_by_id(
        catalog,
        catalog.default_type,
    )


def classification_messages(
    catalog: CatalogSettings,
    title: str,
    description: str,
) -> list[dict[str, Any]]:
    types = [
        {
            'type_id': t.id,
            'name': t.name,
            'kind': t.kind,
            'description': t.description,
        }
        for t in catalog.types
    ]
    system = (
        'You classify FunPay lots into product types by the lot title and '
        'description. Answer with JSON only: {"type_id": "<one of the ids>", '
        '"reason": "<short reason in Russian>"}. If nothing fits, use '
        f'"{catalog.default_type}".'
    )
    user = json.dumps(
        {
            'types': types,
            'lot': {'title': title, 'description': description[:3000]},
        },
        ensure_ascii=False,
    )
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]


def parse_classification(
    catalog: CatalogSettings,
    content: str,
) -> tuple[str, str] | None:
    match = _JSON_RE.search(content or '')
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    type_id = str(data.get('type_id', ''))
    if type_id not in {t.id for t in catalog.types}:
        return None
    return type_id, str(data.get('reason', ''))[:300]


def handoff_hit(ptype: ProductType, text: str) -> str | None:
    lowered = norm(text)
    for word in ptype.handoff_keywords:
        w = norm(word)
        if w and w in lowered:
            return word
    return None
