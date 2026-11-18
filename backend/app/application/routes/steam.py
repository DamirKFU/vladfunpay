from fastapi import APIRouter, Depends

from app.application.deps import current_user, resolve
from app.application.schemas import ProtectSchema
from app.integrations.provider import NotConfiguredError
from app.usecases.errors import ValidationError
from app.usecases.friends import FriendsService

router = APIRouter(
    prefix='/steam',
    tags=['steam'],
    dependencies=[Depends(current_user)],
)


@router.get('/friends', summary='Друзья Steam и заявки')
async def friends_report(
    service: FriendsService = Depends(resolve(FriendsService)),
):
    return await service.report()


@router.post('/friends/refresh', summary='Обновить из Steam')
async def friends_refresh(
    service: FriendsService = Depends(resolve(FriendsService)),
):
    try:
        return await service.refresh()
    except NotConfiguredError as e:
        raise ValidationError(str(e)) from e


@router.post('/protected', summary='Закрепить друга')
async def protect(
    schema: ProtectSchema,
    service: FriendsService = Depends(resolve(FriendsService)),
) -> dict:
    await service.protect(schema.steam_id, schema.note)
    return {'ok': True}


@router.delete('/protected/{steam_id}', summary='Открепить друга')
async def unprotect(
    steam_id: str,
    service: FriendsService = Depends(resolve(FriendsService)),
) -> dict:
    await service.unprotect(steam_id)
    return {'ok': True}
