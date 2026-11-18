from typing import Any

from pydantic import BaseModel, Field


class CredentialsSchema(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordSchema(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class TokenSchema(BaseModel):
    token: str
    username: str


class SettingsPatchSchema(BaseModel):
    """Частичное обновление настроек: секции и поля как в GET /settings."""

    model_config = {'extra': 'allow'}

    def patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ProtectSchema(BaseModel):
    steam_id: str = Field(pattern=r'^\d{17}$')
    note: str = Field(default='', max_length=200)
