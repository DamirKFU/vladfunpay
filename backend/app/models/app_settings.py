from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, TypeVar

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
)
YANDEX_BASE_URL = 'https://llm.api.cloud.yandex.net/v1'


@dataclass
class FunPaySettings:
    golden_key: str = ''
    user_agent: str = DEFAULT_USER_AGENT
    # Подкатегории своих лотов для инструмента «ассортимент».
    # Пусто — берутся из синхронизированных заказов (type_data.node).
    offer_subcategories: list[int] = field(default_factory=list)
    # Автоподнятие лотов (кнопка «Поднять предложения» на FunPay).
    auto_raise: bool = False
    # Категории (игры) для поднятия, например 41 — Dota 2.
    # Пусто — берутся из синхронизированных заказов (game.game_id).
    raise_categories: list[int] = field(default_factory=list)


@dataclass
class YandexSettings:
    api_key: str = ''
    folder_id: str = ''
    model: str = 'yandexgpt/latest'
    base_url: str = YANDEX_BASE_URL
    temperature: float = 0.3


@dataclass
class SteamSettings:
    api_key: str = ''
    steam_id: str = ''
    # Cookie steamcommunity.com для действий с друзьями.
    login_secure: str = ''
    session_id: str = ''


@dataclass
class ReplyTemplate:
    """Готовый ответ без ИИ.

    examples — примеры сообщений покупателя («когда придёт предмет?»):
    шаблон срабатывает, если фраза покупателя похожа на один из примеров.
    keywords — запасной вариант: срабатывает на вхождение слова.
    В reply можно писать {buyer}.
    """

    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    reply: str = ''


@dataclass
class ReplyExample:
    """Пример для ИИ: как ответить на такое сообщение (few-shot)."""

    buyer: str = ''
    reply: str = ''


@dataclass
class BotSettings:
    enabled: bool = False
    poll_interval_sec: int = 5
    reply_delay_sec: int = 7
    max_wait_sec: int = 40
    max_tokens: int = 600
    daily_token_limit: int = 100_000
    chat_daily_replies: int = 40
    only_with_open_orders: bool = True
    max_input_chars: int = 2000
    history_messages: int = 12
    seller_notes: str = ''
    # Ответ покупателю, когда чат сразу уходит владельцу (например,
    # проблема со входом в купленный аккаунт).
    handoff_reply: str = (
        'Передал ваш вопрос продавцу — он ответит лично в ближайшее время.'
    )
    # Правила общения для ИИ. Пусто — стандартный текст (DEFAULT_STYLE).
    # Правила работы с инструментами в коде и не редактируются.
    style_prompt: str = ''
    examples: list[ReplyExample] = field(default_factory=list)
    templates: list[ReplyTemplate] = field(default_factory=list)
    # Насколько фраза покупателя должна совпасть с примером шаблона (0–1).
    template_threshold: float = 0.6


@dataclass
class ProtectedFriend:
    steam_id: str = ''
    note: str = ''


@dataclass
class FriendsSettings:
    protected: list[ProtectedFriend] = field(default_factory=list)
    keep_free_slots: int = 10
    long_friend_days: int = 30
    auto_cleanup: bool = False
    # Как часто обновлять друзей из Steam (для сроков выдачи), 0 — вручную.
    refresh_hours: int = 3
    # Главный выключатель удаления друзей (ручного и автоматического).
    allow_removal: bool = True


@dataclass
class TelegramSettings:
    """Уведомления владельцу в Telegram через своего бота (@BotFather)."""

    bot_token: str = ''
    chat_id: str = ''
    notify_tool_errors: bool = True
    notify_handoff: bool = True
    notify_sandbox: bool = False


class ProductKind:
    GIFT = 'gift'  # подарок Steam: дружба N дней, не больше per_day в день
    TRADE = 'trade'  # обмен по трейд-ссылке
    ACCOUNT = 'account'  # аккаунт: выдаёт автовыдача FunPay
    MANUAL = 'manual'  # другое: продавец выдаёт сам за send_hours

    ALL = (GIFT, TRADE, ACCOUNT, MANUAL)


@dataclass
class ProductType:
    """Тип товара: как его выдавать и как ИИ должен о нём говорить.

    description — для ИИ-классификации: какие лоты относятся к типу
    (ИИ читает описание карточки лота и выбирает тип).
    instructions — для ИИ в чате: как работать с покупателем.
    keywords — быстрое правило без ИИ: слово в названии/описании лота.
    handoff_keywords — если покупатель с открытым заказом этого типа
    пишет такие слова, чат сразу уходит владельцу (без ИИ).
    """

    id: str = ''
    name: str = ''
    kind: str = ProductKind.MANUAL
    description: str = ''
    instructions: str = ''
    keywords: list[str] = field(default_factory=list)
    handoff_keywords: list[str] = field(default_factory=list)
    friend_days: int = 30  # gift
    per_day: int = 8  # gift: сколько подарков продавец отправляет в день
    send_hours: int = 24  # gift: на отправку; trade/manual: срок выдачи


def default_product_types() -> list[ProductType]:
    return [
        ProductType(
            id='dota_gift',
            name='Предмет Dota 2 подарком',
            kind=ProductKind.GIFT,
            description=(
                'Предметы Dota 2 (сеты, арканы, курьеры и т. п.), которые '
                'продавец отправляет подарком в Steam после 30 дней дружбы.'
            ),
            instructions=(
                'Delivered as a Steam gift. Steam lets the seller gift only '
                'after the buyer has been in the friend list for 30 days, and '
                'the seller sends a limited number of gifts per day, so there '
                'is a queue. Ask for the Steam profile link if it is missing. '
                'Ask the buyer to accept the friend request and never remove '
                'the seller from friends: removal restarts the 30 days. '
                'Always '
                'use get_delivery_info for dates and say they are approximate.'
            ),
            keywords=['подарк', 'gift'],
            friend_days=30,
            per_day=8,
            send_hours=24,
        ),
        ProductType(
            id='steam_trade',
            name='Обмен по трейд-ссылке',
            kind=ProductKind.TRADE,
            description=(
                'Предметы, которые передаются обменом Steam по трейд-ссылке '
                'покупателя, без ожидания дружбы.'
            ),
            instructions=(
                'Delivered by a Steam trade offer. Ask for the trade offer '
                'link with token (Steam > Inventory > Trade offers > Who can '
                'send me '
                'trade offers). Remind that the inventory must be public and '
                'Steam Guard may hold the trade.'
            ),
            keywords=['трейд', 'обмен', 'trade'],
            send_hours=24,
        ),
        ProductType(
            id='dota_account',
            name='Аккаунт Dota 2',
            kind=ProductKind.ACCOUNT,
            description=(
                'Аккаунты Dota 2 / Steam: логин, пароль, почта. Выдаются '
                'автовыдачей FunPay сразу после оплаты.'
            ),
            instructions=(
                'The account data is delivered automatically by FunPay right '
                'after payment (in the order). Never write, repeat or guess '
                'logins, passwords or emails yourself. Advise changing the '
                'password and email after the first login. Any login problem '
                '(wrong password, Steam Guard or email code, locked account) '
                'must go to the seller: call request_human.'
            ),
            keywords=['аккаунт', 'акк', 'account', 'логин', 'mmr'],
            handoff_keywords=[
                'войти',
                'зайти',
                'заходит',
                'вход',
                'пароль',
                'логин',
                'guard',
                'гуард',
                'код',
                'почт',
                'заблок',
                'бан',
            ],
        ),
        ProductType(
            id='manual',
            name='Другое (выдаёт продавец)',
            kind=ProductKind.MANUAL,
            description='Всё остальное: продавец выдаёт товар вручную.',
            instructions=(
                'The seller delivers manually within send_hours after '
                'payment. '
                'If the buyer waits longer, call request_human.'
            ),
            send_hours=24,
        ),
    ]


@dataclass
class CatalogSettings:
    types: list[ProductType] = field(default_factory=default_product_types)
    default_type: str = 'dota_gift'
    # Определять тип лота ИИ по описанию карточки (если нет ручного выбора
    # и не сработали слова-ключи).
    classify_with_ai: bool = True


@dataclass
class AppSettings:
    funpay: FunPaySettings = field(default_factory=FunPaySettings)
    yandex: YandexSettings = field(default_factory=YandexSettings)
    steam: SteamSettings = field(default_factory=SteamSettings)
    bot: BotSettings = field(default_factory=BotSettings)
    friends: FriendsSettings = field(default_factory=FriendsSettings)
    catalog: CatalogSettings = field(default_factory=CatalogSettings)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)


# Поля, которые шифруются в базе и никогда не уходят во фронт.
SECRET_FIELDS: tuple[tuple[str, str], ...] = (
    ('funpay', 'golden_key'),
    ('yandex', 'api_key'),
    ('steam', 'api_key'),
    ('steam', 'login_secure'),
    ('steam', 'session_id'),
    ('telegram', 'bot_token'),
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
    (BotSettings, 'templates'): ReplyTemplate,
    (FriendsSettings, 'protected'): ProtectedFriend,
    (BotSettings, 'examples'): ReplyExample,
    (CatalogSettings, 'types'): ProductType,
}


def to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)
