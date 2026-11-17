"""HTTP-клиент выгрузок FunPay: создание, ожидание готовности, скачивание."""

from __future__ import annotations

import logging
import random
import time
import zipfile
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from auth import (
    BASE_URL,
    AppData,
    AuthError,
    check_blocked,
    fetch_app_data,
    mask_secrets,
)

log = logging.getLogger(__name__)

EXPORTS_URL = f"{BASE_URL}/exports/"
CREATE_URL = f"{BASE_URL}/exports/create"

# Как передавать CSRF-токен в POST /exports/create. НЕ ПРОВЕРЕНО:
# другие AJAX-формы FunPay шлют поле csrf_token в теле, но сверьте
# с вкладкой Network и при необходимости смените --csrf-mode.
CsrfMode = Literal["body", "header", "both"]
CSRF_BODY_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ExportStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    DELETED = "deleted"


@dataclass(frozen=True)
class ExportRow:
    export_id: str
    cells: list[str]
    status: ExportStatus
    download_url: str | None
    html: str


class ExportError(RuntimeError):
    pass


class FunPayClient:
    def __init__(
        self,
        session: requests.Session,
        *,
        timeout: float = 30.0,
        min_pause: float = 1.0,
        max_pause: float = 2.0,
        max_retries: int = 5,
        csrf_mode: CsrfMode = "body",
        debug: bool = False,
    ) -> None:
        self.session = session
        self.timeout = timeout
        self.min_pause = min_pause
        self.max_pause = max_pause
        self.max_retries = max_retries
        self.csrf_mode = csrf_mode
        self.debug = debug
        self._last_request = 0.0
        self.app: AppData | None = None

    # --- низкоуровневые запросы -------------------------------------------

    def _throttle(self) -> None:
        wait = random.uniform(self.min_pause, self.max_pause) - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        """Запрос с паузами и повторами (сетевые ошибки, 429, 5xx)."""
        kwargs.setdefault("timeout", self.timeout)
        delay = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.request(method, url, **kwargs)  # type: ignore[arg-type]
            except (requests.ConnectionError, requests.Timeout) as e:
                self._last_request = time.monotonic()
                if attempt == self.max_retries:
                    raise
                log.warning("%s %s: %s; повтор %d через %.0f с", method, url, type(e).__name__, attempt, delay)
            else:
                self._last_request = time.monotonic()
                if resp.status_code not in RETRY_STATUSES or attempt == self.max_retries:
                    return resp
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                log.warning("%s %s: HTTP %d; повтор %d через %.0f с", method, url, resp.status_code, attempt, delay)
            time.sleep(delay + random.uniform(0, 1))
            delay = min(delay * 2, 120)
        raise AssertionError("unreachable")

    def login(self) -> AppData:
        self._throttle()
        self.app = fetch_app_data(self.session, timeout=self.timeout)
        self._last_request = time.monotonic()
        return self.app

    # --- список выгрузок ---------------------------------------------------

    def list_exports(self) -> dict[str, ExportRow]:
        resp = self.request("GET", EXPORTS_URL)
        check_blocked(resp)
        if resp.status_code in (401, 403) or "/account/login" in resp.url:
            raise AuthError(f"HTTP {resp.status_code} на {EXPORTS_URL}")
        resp.raise_for_status()
        return parse_exports_table(resp.text, base_url=resp.url)

    # --- создание ----------------------------------------------------------

    def _create_payload(self, date_from: date | None, date_to: date | None, lot_fields: bool) -> tuple[dict[str, str], dict[str, str]]:
        assert self.app is not None
        data = {
            "type": "orders_seller",
            "from": date_from.isoformat() if date_from else "",
            "to": date_to.isoformat() if date_to else "",
            "format": "jsonl",
        }
        if lot_fields:
            data["lot_fields"] = "on"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": EXPORTS_URL,
            "Origin": BASE_URL,
        }
        if self.csrf_mode in ("body", "both"):
            data[CSRF_BODY_FIELD] = self.app.csrf_token
        if self.csrf_mode in ("header", "both"):
            headers[CSRF_HEADER] = self.app.csrf_token
        return data, headers

    def create_export(self, date_from: date | None, date_to: date | None, *, lot_fields: bool = False) -> str:
        """Создаёт выгрузку и возвращает её id."""
        if self.app is None:
            self.login()
        before = set(self.list_exports())

        refreshed = False
        while True:
            data, headers = self._create_payload(date_from, date_to, lot_fields)
            if self.debug:
                log.info("DEBUG POST %s: поля тела=%s, доп. заголовки=%s", CREATE_URL, sorted(data), sorted(headers))
            resp = self.request("POST", CREATE_URL, data=data, headers=headers, allow_redirects=True)
            check_blocked(resp)
            if self.debug:
                self._dump_response(resp)
            if resp.status_code in (400, 401, 403, 419) and not refreshed:
                log.warning("POST вернул HTTP %d, обновляю CSRF-токен и повторяю один раз", resp.status_code)
                self.login()
                refreshed = True
                continue
            if resp.status_code in (401, 403):
                raise AuthError(f"POST {CREATE_URL} вернул HTTP {resp.status_code} после обновления токена")
            if resp.status_code >= 400:
                raise ExportError(f"POST {CREATE_URL}: HTTP {resp.status_code}: {mask_secrets(resp.text[:500])}")
            break

        export_id = extract_new_id(resp)
        if export_id:
            log.info("Выгрузка создана, id=%s", export_id)
            return export_id

        # Формат ответа неизвестен: ищем строку, которой не было до POST.
        after = self.list_exports()
        new_ids = [i for i in after if i not in before]
        if len(new_ids) == 1:
            log.info("Выгрузка создана (найдена по таблице), id=%s", new_ids[0])
            return new_ids[0]
        raise ExportError(
            "не удалось определить id новой выгрузки; запустите с --debug и пришлите вывод "
            f"(новых строк в таблице: {len(new_ids)})"
        )

    def _dump_response(self, resp: requests.Response) -> None:
        chain = [f"{r.status_code} {r.url}" for r in resp.history] + [f"{resp.status_code} {resp.url}"]
        log.info("DEBUG ответ: цепочка=%s", " -> ".join(chain))
        log.info("DEBUG ответ: Content-Type=%s, заголовки=%s", resp.headers.get("Content-Type"), sorted(resp.headers))
        log.info("DEBUG ответ: тело (первые 2000 симв.):\n%s", mask_secrets(resp.text[:2000]))

    # --- ожидание и скачивание --------------------------------------------

    def wait_ready(self, export_id: str, *, interval: float = 20.0, timeout: float = 600.0) -> str:
        """Опрос /exports/ до появления ссылки. Возвращает URL скачивания."""
        deadline = time.monotonic() + timeout
        while True:
            row = self.list_exports().get(export_id)
            if row is None:
                raise ExportError(f"выгрузка {export_id} не найдена в таблице /exports/")
            if self.debug:
                log.info("DEBUG строка таблицы:\n%s", mask_secrets(row.html))
            log.info("Выгрузка %s: %s (%s)", export_id, row.status.value, " | ".join(row.cells))
            if row.status is ExportStatus.READY and row.download_url:
                return row.download_url
            if row.status is ExportStatus.DELETED:
                raise ExportError(f"выгрузка {export_id}: файл удалён")
            if time.monotonic() + interval > deadline:
                raise ExportError(f"выгрузка {export_id} не готова за {timeout:.0f} с")
            time.sleep(interval)

    def download(self, url: str, dest: Path) -> Path:
        """Скачивает файл потоково (без загрузки в память)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        resp = self.request("GET", url, stream=True)
        try:
            if "text/html" in resp.headers.get("Content-Type", ""):
                # Вместо файла пришла HTML-страница: логин, капча или ошибка.
                check_blocked(resp)
                if "/account/login" in resp.url:
                    raise AuthError("редирект на логин при скачивании")
            if resp.status_code in (401, 403):
                raise AuthError(f"HTTP {resp.status_code} при скачивании")
            resp.raise_for_status()
            if self.debug:
                log.info("DEBUG скачивание: Content-Type=%s, Content-Disposition=%s",
                         resp.headers.get("Content-Type"), resp.headers.get("Content-Disposition"))
            size = 0
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    f.write(chunk)
                    size += len(chunk)
        finally:
            resp.close()
        log.info("Скачано %d байт", size)
        if zipfile.is_zipfile(tmp):
            unpack_zip(tmp, dest)
            tmp.unlink()
        else:
            tmp.replace(dest)
        log.info("Сохранено %s", dest)
        return dest


def unpack_zip(archive: Path, dest: Path) -> None:
    """Распаковывает JSONL из ZIP в dest потоково.

    FunPay отдаёт выгрузку архивом с одним файлом funpay_sales_*.jsonl.
    Имена внутри архива для путей не используются; если файлов несколько,
    они склеиваются в один.
    """
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        jsonl = [m for m in members if m.filename.lower().endswith(".jsonl")] or members
        if not jsonl:
            raise ExportError(f"в архиве {archive.name} нет файлов")
        log.info("В архиве: %s", ", ".join(f"{m.filename} ({m.file_size} байт)" for m in jsonl))
        with dest.open("wb") as out:
            for m in jsonl:
                with zf.open(m) as src:
                    last = b""
                    while chunk := src.read(64 * 1024):
                        out.write(chunk)
                        last = chunk
                if last and not last.endswith(b"\n"):
                    out.write(b"\n")


# --- разбор HTML/ответов (чистые функции, покрыты тестами) -------------------


def parse_exports_table(html: str, base_url: str = EXPORTS_URL) -> dict[str, ExportRow]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(".js-exports-table")
    rows: dict[str, ExportRow] = {}
    if table is None:
        return rows
    for tr in table.select("tr[data-export-id]"):
        export_id = str(tr.get("data-export-id"))
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        link = tr.select_one("a.js-export-download")
        href = link.get("href") if link else None
        text = tr.get_text(" ", strip=True).lower()
        if href:
            status = ExportStatus.READY
        elif "файл удалён" in text or "файл удален" in text:
            status = ExportStatus.DELETED
        else:
            status = ExportStatus.PENDING
        rows[export_id] = ExportRow(
            export_id=export_id,
            cells=cells,
            status=status,
            download_url=urljoin(base_url, str(href)) if href else None,
            html=str(tr),
        )
    return rows


def _new_param(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("new")
    return values[0] if values else None


def extract_new_id(resp: requests.Response) -> str | None:
    """id из редиректа /exports/?new=<id> (Location, итоговый URL или JSON)."""
    for r in [*resp.history, resp]:
        for candidate in (r.headers.get("Location", ""), r.url):
            if candidate and (found := _new_param(urljoin(BASE_URL, candidate))):
                return found
    if "json" in resp.headers.get("Content-Type", ""):
        try:
            payload = resp.json()
        except ValueError:
            return None
        stack: list[object] = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, str) and "new=" in item:
                if found := _new_param(urljoin(BASE_URL, item)):
                    return found
    return None
