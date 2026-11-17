"""Выгрузка продаж через встроенный экспорт FunPay (/exports/).

Перенесено из legacy/client.py и проверено на реальном аккаунте:
POST /exports/create с полем csrf_token отвечает JSON
{"url": ".../exports/?new=<id>"}, файл приходит ZIP-архивом с одним
funpay_sales_*.jsonl.
"""

import asyncio
import io
import json
import logging
import random
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.core import messages
from app.integrations.funpay.base import (
    BaseOrderExporter,
    MarketplaceAuthError,
    MarketplaceError,
)

log = logging.getLogger('funpay.exports')

BASE_URL = 'https://funpay.com'
TRADE_URL = f'{BASE_URL}/orders/trade'
EXPORTS_URL = f'{BASE_URL}/exports/'
CREATE_URL = f'{BASE_URL}/exports/create'
RETRY_STATUSES = {429, 500, 502, 503, 504}
CAPTCHA_MARKERS = ('g-recaptcha', 'h-captcha', 'cf-challenge', 'cf-turnstile')


@dataclass
class FunPayExporter(BaseOrderExporter):
    golden_key: str
    user_agent: str
    poll_interval: float = 15.0
    poll_timeout: float = 900.0
    min_pause: float = 1.0
    max_pause: float = 2.0
    timeout: float = 60.0

    async def export(
        self,
        date_from: date | None,
        date_to: date,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._export_sync, date_from, date_to)

    # --- синхронная часть (requests) -------------------------------------

    def _export_sync(
        self,
        date_from: date | None,
        date_to: date,
    ) -> list[dict[str, Any]]:
        session = self._session()
        self._last = 0.0
        csrf = self._csrf(session)
        export_id = self._create(session, csrf, date_from, date_to)
        url = self._wait(session, export_id)
        return self._download(session, url)

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                'User-Agent': self.user_agent,
                'Accept-Language': 'ru,en;q=0.8',
            },
        )
        s.cookies.set('golden_key', self.golden_key, domain='funpay.com')
        return s

    def _request(
        self,
        session: requests.Session,
        method: str,
        url: str,
        **kw: Any,
    ) -> requests.Response:
        kw.setdefault('timeout', self.timeout)
        delay = 2.0
        for attempt in range(1, 6):
            wait = random.uniform(self.min_pause, self.max_pause)
            wait -= time.monotonic() - self._last
            if wait > 0:
                time.sleep(wait)
            try:
                resp = session.request(method, url, **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                self._last = time.monotonic()
                if attempt == 5:
                    raise MarketplaceError(str(e)) from e
                log.warning('%s %s: %s, повтор %d', method, url, e, attempt)
            else:
                self._last = time.monotonic()
                if resp.status_code not in RETRY_STATUSES or attempt == 5:
                    self._check(resp)
                    return resp
                log.warning(
                    '%s %s: HTTP %d, повтор %d',
                    method,
                    url,
                    resp.status_code,
                    attempt,
                )
            time.sleep(delay + random.uniform(0, 1))
            delay = min(delay * 2, 60)
        raise AssertionError('unreachable')

    @staticmethod
    def _check(resp: requests.Response) -> None:
        if 'text/html' not in resp.headers.get('Content-Type', ''):
            return
        text = resp.text[:200_000].lower()
        if any(m in text for m in CAPTCHA_MARKERS):
            raise MarketplaceError(messages.FUNPAY_BLOCKED)
        if resp.status_code in (401, 403) or '/account/login' in resp.url:
            raise MarketplaceAuthError(messages.FUNPAY_AUTH_FAILED)

    def _csrf(self, session: requests.Session) -> str:
        resp = self._request(session, 'GET', TRADE_URL)
        return parse_app_data(resp.text)[0]

    def _create(
        self,
        session: requests.Session,
        csrf: str,
        date_from: date | None,
        date_to: date,
    ) -> str:
        data = {
            'type': 'orders_seller',
            'from': date_from.isoformat() if date_from else '',
            'to': date_to.isoformat(),
            'format': 'jsonl',
            'csrf_token': csrf,
        }
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': TRADE_URL}
        resp = self._request(
            session,
            'POST',
            CREATE_URL,
            data=data,
            headers=headers,
        )
        if resp.status_code >= 400:
            raise MarketplaceError(
                messages.FUNPAY_EXPORT_FAILED.format(
                    f'HTTP {resp.status_code}',
                ),
            )
        export_id = extract_new_id(resp)
        if not export_id:
            raise MarketplaceError(
                messages.FUNPAY_EXPORT_FAILED.format('нет id выгрузки'),
            )
        log.info('Выгрузка FunPay создана: %s', export_id)
        return export_id

    def _wait(self, session: requests.Session, export_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout
        while True:
            resp = self._request(session, 'GET', EXPORTS_URL)
            row = parse_exports_table(resp.text).get(export_id)
            if row and row.get('url'):
                return urljoin(EXPORTS_URL, row['url'])
            if row and row.get('deleted'):
                raise MarketplaceError(
                    messages.FUNPAY_EXPORT_FAILED.format('файл удалён'),
                )
            if time.monotonic() + self.poll_interval > deadline:
                raise MarketplaceError(
                    messages.FUNPAY_EXPORT_FAILED.format('не дождались'),
                )
            time.sleep(self.poll_interval)

    def _download(
        self,
        session: requests.Session,
        url: str,
    ) -> list[dict[str, Any]]:
        resp = self._request(session, 'GET', url)
        resp.raise_for_status()
        return parse_export_payload(resp.content)


# --- чистые функции разбора (покрыты тестами) ------------------------------


def parse_app_data(html: str) -> tuple[str, int]:
    soup = BeautifulSoup(html, 'html.parser')
    body = soup.find('body')
    raw = body.get('data-app-data') if body else None
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    user_id = int(data.get('userId') or 0)
    csrf = str(data.get('csrf-token') or '')
    if not user_id or not csrf:
        raise MarketplaceAuthError(messages.FUNPAY_AUTH_FAILED)
    return csrf, user_id


def parse_exports_table(html: str) -> dict[str, dict[str, Any]]:
    soup = BeautifulSoup(html, 'html.parser')
    rows: dict[str, dict[str, Any]] = {}
    for tr in soup.select('.js-exports-table tr[data-export-id]'):
        link = tr.select_one('a.js-export-download')
        text = tr.get_text(' ', strip=True).lower()
        rows[str(tr.get('data-export-id'))] = {
            'url': link.get('href') if link else None,
            'deleted': 'файл удал' in text,
        }
    return rows


def extract_new_id(resp: requests.Response) -> str | None:
    candidates = [r.headers.get('Location', '') for r in resp.history]
    candidates.append(resp.url)
    if 'json' in resp.headers.get('Content-Type', ''):
        try:
            candidates.append(str(resp.json().get('url', '')))
        except (ValueError, AttributeError):
            pass
    for url in candidates:
        values = parse_qs(urlparse(url).query).get('new')
        if values:
            return values[0]
    return None


def parse_export_payload(content: bytes) -> list[dict[str, Any]]:
    """ZIP с JSONL или сам JSONL -> список записей."""
    if content[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            members = [
                m
                for m in zf.infolist()
                if m.filename.lower().endswith('.jsonl')
            ]
            content = b'\n'.join(zf.read(m) for m in members)
    records = []
    for line in content.decode('utf-8-sig').splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
