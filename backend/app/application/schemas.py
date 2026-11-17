from datetime import datetime
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


class SteamIdsSchema(BaseModel):
    steam_ids: list[str] = Field(min_length=1, max_length=200)


class ProtectSchema(BaseModel):
    steam_id: str = Field(pattern=r'^\d{17}$')
    note: str = Field(default='', max_length=200)


class SandboxChatSchema(BaseModel):
    buyer_name: str = Field(default='test_buyer', max_length=64)


class SandboxMessageSchema(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class SandboxOrderSchema(BaseModel):
    chat_id: str
    offer_id: str | None = None
    title: str = Field(default='', max_length=200)
    price: float = Field(default=0, ge=0)


class OrderStatusSchema(BaseModel):
    status: str = Field(pattern=r'^(paid|closed|refunded)$')


class OfferSchema(BaseModel):
    offer_id: str = ''
    title: str = Field(min_length=1, max_length=200)
    price: float = Field(ge=0)
    amount: int | None = Field(default=None, ge=0)
    category: str = ''
    auto_delivery: bool = False
    description: str = Field(default='', max_length=5000)


class FriendshipSchema(BaseModel):
    relationship: str | None = Field(
        default=None,
        pattern=r'^(friend|invite_sent|invite_received)$',
    )
    since: datetime | None = None
