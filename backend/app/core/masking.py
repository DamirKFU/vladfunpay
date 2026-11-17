import re
from threading import Lock

_COOKIE_RE = re.compile(
    r'(?i)((?:golden_key|PHPSESSID|steamLoginSecure|sessionid)=)[^;\s&"\']+',
)
_AUTH_RE = re.compile(r'(?i)((?:Api-Key|Bearer)\s+)[A-Za-z0-9._\-]+')
MIN_SECRET_LEN = 6


class SecretMasker:
    """Вырезает секреты из текста логов и ошибок."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = Lock()

    def register(self, value: str) -> None:
        if value and len(value) >= MIN_SECRET_LEN:
            with self._lock:
                self._secrets.add(value)

    def mask(self, text: str) -> str:
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, '***')
        text = _COOKIE_RE.sub(r'\1***', text)
        return _AUTH_RE.sub(r'\1***', text)


masker = SecretMasker()
