"""Автоподнятие лотов FunPay («Поднять предложения»).

FunPay разрешает поднимать категорию раз в несколько часов и сам говорит,
сколько ждать (wait). Следующую попытку ставим по этому ответу; при ошибке
без срока — через RETRY_AFTER_ERROR.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.integrations.funpay.base import BaseLotRaiser
from app.integrations.provider import BaseIntegrations, NotConfiguredError
from app.models.app_settings import AppSettings
from app.repositories.base import BaseOrderRepository
from app.usecases.errors import ValidationError
from app.usecases.settings import SettingsService

log = logging.getLogger('funpay.raise')
RETRY_AFTER_ERROR = timedelta(minutes=30)
MIN_WAIT = timedelta(minutes=5)


@dataclass
class CategoryState:
    category_id: int
    next_at: datetime | None = None
    last_at: datetime | None = None
    ok: bool | None = None
    message: str = ''


@dataclass
class RaiseService:
    settings: SettingsService
    orders: BaseOrderRepository
    integrations: BaseIntegrations
    _state: dict[int, CategoryState] = field(
        default_factory=dict,
        init=False,
    )
    _raiser: BaseLotRaiser | None = field(default=None, init=False)
    _key: str = field(default='', init=False)

    async def categories(self, s: AppSettings) -> list[int]:
        return s.funpay.raise_categories or await self.orders.game_ids()

    async def status(self) -> dict:
        s = await self.settings.get()
        cats = await self.categories(s)
        return {
            'enabled': s.funpay.auto_raise,
            'categories': [self._state.get(c, CategoryState(c)) for c in cats],
        }

    async def tick(self, now: datetime | None = None, force: bool = False):
        """Поднимает категории, у которых подошёл срок. force — все сразу."""
        now = now or datetime.now(timezone.utc)
        s = await self.settings.get()
        if not (s.funpay.auto_raise or force):
            return []
        try:
            raiser = await self._get_raiser(s)
        except NotConfiguredError as e:
            log.warning('Автоподнятие: %s', e)
            if force:
                raise ValidationError(str(e)) from e
            return []
        done = []
        for category in await self.categories(s):
            state = self._state.setdefault(category, CategoryState(category))
            if not force and state.next_at and state.next_at > now:
                continue
            await self._raise_one(raiser, state, now)
            done.append(state)
        if not done and force:
            text = (
                'нет категорий для поднятия: синхронизируйте продажи или '
                'укажите ID игр в настройках'
            )
            log.warning('Автоподнятие: %s', text)
            raise ValidationError(text)
        return done

    async def _raise_one(
        self,
        raiser: BaseLotRaiser,
        state: CategoryState,
        now: datetime,
    ) -> None:
        state.last_at = now
        try:
            result = await raiser.raise_lots(state.category_id)
        except Exception as e:  # сеть, вход, разметка FunPay
            log.warning('Автоподнятие %s упало: %s', state.category_id, e)
            state.ok, state.message = False, str(e)
            state.next_at = now + RETRY_AFTER_ERROR
            await self._reset_raiser()
            return
        state.ok, state.message = result.ok, result.message
        wait = timedelta(seconds=result.wait_sec)
        if not result.ok and not result.wait_sec:
            wait = RETRY_AFTER_ERROR
        state.next_at = now + max(wait, MIN_WAIT)
        log.info(
            'Автоподнятие %s: %s, следующее после %s',
            state.category_id,
            result.message or ('ок' if result.ok else 'ошибка'),
            state.next_at.isoformat(timespec='minutes'),
        )

    async def _get_raiser(self, s: AppSettings) -> BaseLotRaiser:
        key = f'{s.funpay.golden_key}|{s.funpay.user_agent}'
        if self._raiser is None or key != self._key:
            await self._reset_raiser()
            self._raiser = self.integrations.raiser(s)
            self._key = key
        return self._raiser

    async def _reset_raiser(self) -> None:
        if self._raiser is not None:
            await self._raiser.close()
        self._raiser, self._key = None, ''
