from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, TypeVar

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
)


@dataclass
class FunPaySettings:
    golden_key: str = ''
    user_agent: str = DEFAULT_USER_AGENT
    # Автоподнятие лотов (кнопка «Поднять предложения» на FunPay).
    auto_raise: bool = False
    # Категории (игры) для поднятия, например 41 — Dota 2.
    # Пусто — берутся из синхронизированных заказов (game.game_id).
    raise_categories: list[int] = field(default_factory=list)


@dataclass
class SteamSettings:
    api_key: str = ''
    steam_id: str = ''
    # Cookie steamcommunity.com для списка заявок.
    login_secure: str = ''


@dataclass
class ProtectedFriend:
    steam_id: str = ''
    note: str = ''


@dataclass
class FriendsSettings:
    protected: list[ProtectedFriend] = field(default_factory=list)
    # Как часто обновлять друзей из Steam, 0 — вручную.
    refresh_hours: int = 3


@dataclass
class AppSettings:
    funpay: FunPaySettings = field(default_factory=FunPaySettings)
    steam: SteamSettings = field(default_factory=SteamSettings)
    friends: FriendsSettings = field(default_factory=FriendsSettings)


# Поля, которые шифруются в базе и никогда не уходят во фронт.
SECRET_FIELDS: tuple[tuple[str, str], ...] = (
    ('funpay', 'golden_key'),
    ('steam', 'api_key'),
    ('steam', 'login_secure'),
)

T = TypeVar('T')


def from_dict(cls: type[T], data: Any) -> T:
    """Собирает dataclass из dict, игнорируя лишние ключи.

    Новые поля в коде получают значения по умолчанию, поэтому старые
    настройки в базе не ломаются после обновления.
    """
    if not isinstance(data, dict):
        return cls()
    kwargs: dict[str, Any] = {}
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name not in data:
            continue
        kwargs[f.name] = _coerce(cls, f.name, data[f.name])
    return cls(**kwargs)


def _coerce(owner: type, name: str, value: Any) -> Any:
    sample = getattr(owner(), name)
    if is_dataclass(sample):
        return from_dict(type(sample), value)
    if isinstance(sample, list) and value and isinstance(value, list):
        item_type = _LIST_ITEMS.get((owner, name))
        if item_type:
            return [from_dict(item_type, v) for v in value]
    return value


_LIST_ITEMS: dict[tuple[type, str], type] = {
    (FriendsSettings, 'protected'): ProtectedFriend,
}


def to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
