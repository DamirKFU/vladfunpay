"""Каталог лотов, типы товаров и аккаунты в автовыдачу."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.application.deps import current_user, resolve
from app.models.app_settings import default_product_types
from app.models.domain import Channel
from app.usecases.lots import LotCatalogService

router = APIRouter(tags=['lots'], dependencies=[Depends(current_user)])


class LotTypeSchema(BaseModel):
    type_id: str | None = Field(
        default=None,
        description='None — снова определять тип автоматически',
    )


class AccountSchema(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    email: str = Field(default='', max_length=200)
    email_password: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=300)


class AccountsSchema(BaseModel):
    accounts: list[AccountSchema] = Field(min_length=1, max_length=200)


@router.get('/catalog/presets', summary='Готовые типы товаров')
async def presets() -> list:
    return default_product_types()


@router.get('/lots/{channel}', summary='Лоты и их типы')
async def list_lots(
    channel: Channel,
    service: LotCatalogService = Depends(resolve(LotCatalogService)),
):
    return await service.all_lots(channel)


@router.post('/lots/{channel}/sync', summary='Забрать лоты и описания')
async def sync_lots(
    channel: Channel,
    service: LotCatalogService = Depends(resolve(LotCatalogService)),
):
    return await service.sync(channel)


@router.put('/lots/{channel}/{lot_id}/type', summary='Тип лота вручную')
async def set_lot_type(
    channel: Channel,
    lot_id: str,
    schema: LotTypeSchema,
    service: LotCatalogService = Depends(resolve(LotCatalogService)),
):
    return await service.set_type(channel, lot_id, schema.type_id)


@router.post(
    '/lots/{channel}/{lot_id}/accounts',
    summary='Добавить аккаунты в автовыдачу лота (у нас не хранятся)',
)
async def add_accounts(
    channel: Channel,
    lot_id: str,
    schema: AccountsSchema,
    service: LotCatalogService = Depends(resolve(LotCatalogService)),
):
    return await service.add_accounts(
        channel,
        lot_id,
        [a.model_dump() for a in schema.accounts],
    )
