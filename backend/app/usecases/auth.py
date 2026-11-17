import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core import messages
from app.core.security import (
    SecretBox,
    create_token,
    hash_password,
    read_token,
    verify_password,
)
from app.models.domain import User
from app.repositories.base import BaseUserRepository
from app.settings import Config
from app.usecases.errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    TooManyAttemptsError,
    ValidationError,
)

log = logging.getLogger('auth')
MIN_PASSWORD = 8
ATTEMPTS_WINDOW_SEC = 60
ATTEMPTS_LIMIT = 5


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValidationError(messages.AUTH_PASSWORD_WEAK)


@dataclass
class LoginLimiter:
    """Не больше 5 неудачных попыток за минуту с одного адреса."""

    _attempts: dict[str, deque[float]] = field(
        default_factory=lambda: defaultdict(deque),
    )

    def check(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._attempts[key]
        while attempts and now - attempts[0] > ATTEMPTS_WINDOW_SEC:
            attempts.popleft()
        if len(attempts) >= ATTEMPTS_LIMIT:
            log.warning('Вход заблокирован на минуту', extra={'client': key})
            raise TooManyAttemptsError(messages.AUTH_TOO_MANY_ATTEMPTS)

    def fail(self, key: str) -> None:
        self._attempts[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


@dataclass(frozen=True)
class AuthService:
    users: BaseUserRepository
    box: SecretBox
    config: Config
    limiter: LoginLimiter

    async def needs_setup(self) -> bool:
        return await self.users.count() == 0

    async def setup(self, username: str, password: str) -> str:
        if not await self.needs_setup():
            raise ConflictError(messages.AUTH_SETUP_DONE)
        await self.create_user(username, password)
        return self._token(username)

    async def login(self, username: str, password: str, client: str) -> str:
        self.limiter.check(client)
        user = await self.users.get(username.strip())
        if user is None or not verify_password(password, user.password_hash):
            self.limiter.fail(client)
            log.warning(
                'Неудачный вход: %s',
                username.strip()[:64],
                extra={'client': client},
            )
            raise AuthError(messages.AUTH_INVALID)
        self.limiter.reset(client)
        log.info('Вход: %s', user.username, extra={'client': client})
        return self._token(user.username)

    async def current_user(self, token: str) -> User:
        username = read_token(self.box, token)
        user = await self.users.get(username) if username else None
        if user is None:
            raise AuthError(messages.AUTH_TOKEN_INVALID)
        return user

    async def list_users(self) -> list[User]:
        return await self.users.list()

    async def create_user(self, username: str, password: str) -> User:
        username = username.strip()
        _check_password(password)
        if not username:
            raise ValidationError(messages.AUTH_INVALID)
        if await self.users.get(username):
            raise ConflictError(messages.USER_EXISTS.format(username))
        user = User(
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.now(timezone.utc),
        )
        await self.users.save(user)
        log.info('Создан пользователь %s', username)
        return user

    async def delete_user(self, username: str) -> None:
        if await self.users.get(username) is None:
            raise NotFoundError(messages.USER_NOT_FOUND.format(username))
        if await self.users.count() <= 1:
            raise ConflictError(messages.USER_LAST_ONE)
        await self.users.delete(username)
        log.info('Удалён пользователь %s', username)

    async def change_password(self, user: User, password: str) -> None:
        _check_password(password)
        user.password_hash = hash_password(password)
        await self.users.save(user)
        log.info('Пароль изменён: %s', user.username)

    def _token(self, username: str) -> str:
        return create_token(self.box, username, self.config.token_ttl_hours)
