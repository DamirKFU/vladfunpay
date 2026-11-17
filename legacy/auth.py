"""Авторизация на FunPay: cookie сессии, CSRF-токен, проверка входа.

Секреты читаются только из окружения (или .env). Они никогда не логируются:
для вывода используйте mask_secrets() / SecretsFilter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

log = logging.getLogger(__name__)

BASE_URL = "https://funpay.com"
DOMAIN = "funpay.com"
TRADE_URL = f"{BASE_URL}/orders/trade"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)

ENV_GOLDEN_KEY = "FUNPAY_GOLDEN_KEY"
ENV_PHPSESSID = "FUNPAY_PHPSESSID"

EXIT_AUTH = 2
EXIT_BLOCKED = 3


class AuthError(RuntimeError):
    """Cookie устарели или вход не выполнен (код выхода 2)."""

    exit_code = EXIT_AUTH

    def __init__(self, detail: str = "") -> None:
        msg = "cookie устарели, обновите FUNPAY_GOLDEN_KEY и FUNPAY_PHPSESSID"
        super().__init__(f"{msg} ({detail})" if detail else msg)


class BlockedError(RuntimeError):
    """Сайт показал капчу или блокировку. Обходить не пытаемся."""

    exit_code = EXIT_BLOCKED


@dataclass(frozen=True)
class Credentials:
    golden_key: str
    phpsessid: str

    def values(self) -> list[str]:
        return [self.golden_key, self.phpsessid]


@dataclass(frozen=True)
class AppData:
    csrf_token: str
    user_id: int


# --- маскирование ------------------------------------------------------------

_registered_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Добавляет значение в список маскируемых (cookie, CSRF-токен)."""
    if value and len(value) >= 4:
        _registered_secrets.add(value)


def mask_secrets(text: str) -> str:
    """Заменяет известные секреты и значения заголовка Cookie на ***."""
    for secret in sorted(_registered_secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = re.sub(r"(?i)(cookie:\s*)[^\r\n]+", r"\1***", text)
    text = re.sub(r"(?i)((?:golden_key|PHPSESSID)=)[^;\s&\"']+", r"\1***", text)
    return text


class SecretsFilter(logging.Filter):
    """Фильтр логов: маскирует секреты в любом сообщении."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = None
        return True


# --- загрузка cookie и сессия ------------------------------------------------


def load_credentials(env_file: str | None = ".env") -> Credentials:
    if env_file:
        load_dotenv(env_file, override=False)
    golden_key = os.environ.get(ENV_GOLDEN_KEY, "").strip()
    phpsessid = os.environ.get(ENV_PHPSESSID, "").strip()
    missing = [n for n, v in ((ENV_GOLDEN_KEY, golden_key), (ENV_PHPSESSID, phpsessid)) if not v]
    if missing:
        raise AuthError("не заданы переменные: " + ", ".join(missing))
    creds = Credentials(golden_key, phpsessid)
    for v in creds.values():
        register_secret(v)
    return creds


def build_session(creds: Credentials) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "ru,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }
    )
    s.cookies.set("golden_key", creds.golden_key, domain=DOMAIN, path="/")
    s.cookies.set("PHPSESSID", creds.phpsessid, domain=DOMAIN, path="/")
    return s


# --- разбор страницы ---------------------------------------------------------

_CAPTCHA_MARKERS = ("g-recaptcha", "h-captcha", "cf-challenge", "cf-turnstile", "captcha")


def check_blocked(resp: requests.Response) -> None:
    """Останавливается при капче/блокировке."""
    text = resp.text[:200_000].lower() if resp.content else ""
    if resp.status_code in (403, 429, 503) and ("cloudflare" in text or "captcha" in text):
        raise BlockedError(f"сайт показал капчу/блокировку (HTTP {resp.status_code}); пройдите её в браузере")
    if any(m in text for m in _CAPTCHA_MARKERS) and "data-app-data" not in text:
        raise BlockedError("на странице капча; пройдите её в браузере и обновите cookie")


def has_login_form(soup: BeautifulSoup) -> bool:
    for form in soup.find_all("form"):
        action = (form.get("action") or "").lower()
        if "account/login" in action:
            return True
        if form.find("input", attrs={"type": "password"}):
            return True
    return False


def parse_app_data(html: str) -> AppData:
    """Достаёт csrf-token и userId из <body data-app-data>, проверяет вход."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body")
    raw = body.get("data-app-data") if body else None
    if not raw:
        raise AuthError("в <body> нет data-app-data")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AuthError(f"data-app-data не JSON: {e}") from e

    try:
        user_id = int(data.get("userId") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id == 0 or has_login_form(soup):
        raise AuthError("сайт открыл страницу как гостю")

    csrf = str(data.get("csrf-token") or "")
    if not csrf:
        raise AuthError("в data-app-data нет csrf-token")
    register_secret(csrf)
    return AppData(csrf_token=csrf, user_id=user_id)


def fetch_app_data(session: requests.Session, timeout: float = 30.0) -> AppData:
    """GET /orders/trade и проверка, что вошёл нужный аккаунт."""
    resp = session.get(TRADE_URL, timeout=timeout, allow_redirects=True)
    check_blocked(resp)
    if resp.status_code in (401, 403):
        raise AuthError(f"HTTP {resp.status_code} на {TRADE_URL}")
    if "/account/login" in resp.url:
        raise AuthError("редирект на страницу логина")
    resp.raise_for_status()
    app = parse_app_data(resp.text)
    log.info("Вход выполнен, userId=%s", app.user_id)
    return app
