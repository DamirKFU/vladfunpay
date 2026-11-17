import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


@dataclass(frozen=True)
class Config:
    """Настройки процесса из окружения.

    Всё, что вводит пользователь (ключи FunPay, Яндекса, Steam, параметры
    бота), хранится в базе и редактируется во фронте, а не здесь.
    """

    mongo_url: str = field(
        default_factory=lambda: _env('MONGO_URL', 'mongodb://mongo:27017'),
    )
    mongo_db: str = field(default_factory=lambda: _env('MONGO_DB', 'funpay'))
    data_dir: Path = field(
        default_factory=lambda: Path(_env('DATA_DIR', '/data')),
    )
    token_ttl_hours: int = field(
        default_factory=lambda: int(_env('TOKEN_TTL_HOURS', '72')),
    )
    log_level: str = field(default_factory=lambda: _env('LOG_LEVEL', 'INFO'))
    log_ttl_days: int = field(
        default_factory=lambda: int(_env('LOG_TTL_DAYS', '30')),
    )
    run_workers: bool = field(
        default_factory=lambda: _env('RUN_WORKERS', '1') == '1',
    )

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / 'secret.key'
