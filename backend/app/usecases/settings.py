import logging
from dataclasses import dataclass
from typing import Any

from app.core.masking import masker
from app.core.security import SecretBox, mask
from app.models.app_settings import (
    SECRET_FIELDS,
    AppSettings,
    from_dict,
    to_dict,
)
from app.repositories.base import BaseSettingsRepository

log = logging.getLogger('settings')


@dataclass(frozen=True)
class SettingsService:
    """Настройки проекта из админки. Секреты в базе зашифрованы."""

    repository: BaseSettingsRepository
    box: SecretBox

    async def get(self) -> AppSettings:
        data = await self.repository.load()
        for section, name in SECRET_FIELDS:
            token = data.get(section, {}).get(name)
            if token:
                value = self.box.decrypt(token)
                data[section][name] = value
                masker.register(value)
        return from_dict(AppSettings, data)

    async def public(self) -> dict[str, Any]:
        """Настройки для фронта: вместо секретов — признак и хвост."""
        data = to_dict(await self.get())
        for section, name in SECRET_FIELDS:
            value = data[section][name]
            data[section][name] = {'is_set': bool(value), 'hint': mask(value)}
        return data

    async def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Частичное обновление.

        Секрет: строка — новое значение, None — стереть, нет ключа —
        оставить как есть. Пустую строку считаем «оставить», чтобы пустое
        поле в форме не стирало ключ.
        """
        current = to_dict(await self.get())
        secrets = {}
        for section, name in SECRET_FIELDS:
            sec_patch = patch.get(section)
            if not isinstance(sec_patch, dict) or name not in sec_patch:
                continue
            value = sec_patch.pop(name)
            if value is None:
                secrets[(section, name)] = ''
            elif isinstance(value, str) and value.strip():
                secrets[(section, name)] = value.strip()
        merged = _merge(current, patch)
        for (section, name), value in secrets.items():
            merged[section][name] = value
        settings = from_dict(AppSettings, merged)
        changed = _changed_fields(current, to_dict(settings))
        await self._save(settings)
        log.info(
            'Настройки изменены: %s',
            ', '.join(changed) or 'без изменений',
        )
        return await self.public()

    async def save(self, settings: AppSettings) -> None:
        await self._save(settings)

    async def _save(self, settings: AppSettings) -> None:
        data = to_dict(settings)
        for section, name in SECRET_FIELDS:
            value = data[section][name]
            data[section][name] = self.box.encrypt(value) if value else ''
            masker.register(value)
        await self.repository.save(data)


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _changed_fields(
    old: dict[str, Any],
    new: dict[str, Any],
    prefix: str = '',
) -> list[str]:
    """Имена изменённых полей (без значений: там бывают ключи)."""
    result = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        name = f'{prefix}{key}'
        if isinstance(a, dict) and isinstance(b, dict):
            result.extend(_changed_fields(a, b, name + '.'))
        elif a != b:
            result.append(name)
    return result
