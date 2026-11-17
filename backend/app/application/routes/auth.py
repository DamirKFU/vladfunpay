from http import HTTPStatus

from fastapi import APIRouter, Depends, Request

from app.application.deps import client_key, current_user, resolve
from app.application.schemas import (
    CredentialsSchema,
    PasswordSchema,
    TokenSchema,
)
from app.models.domain import User
from app.usecases.auth import AuthService

router = APIRouter(tags=['auth'])


def _user(user: User) -> dict:
    return {'username': user.username, 'created_at': user.created_at}


@router.get('/auth/state', summary='Нужен ли первый администратор')
async def auth_state(
    auth: AuthService = Depends(resolve(AuthService)),
) -> dict:
    return {'needs_setup': await auth.needs_setup()}


@router.post(
    '/auth/setup',
    status_code=HTTPStatus.CREATED,
    summary='Создать первого администратора',
)
async def setup(
    schema: CredentialsSchema,
    auth: AuthService = Depends(resolve(AuthService)),
) -> TokenSchema:
    token = await auth.setup(schema.username, schema.password)
    return TokenSchema(token=token, username=schema.username.strip())


@router.post('/auth/login', summary='Вход')
async def login(
    schema: CredentialsSchema,
    request: Request,
    auth: AuthService = Depends(resolve(AuthService)),
) -> TokenSchema:
    token = await auth.login(
        schema.username,
        schema.password,
        client_key(request),
    )
    return TokenSchema(token=token, username=schema.username.strip())


@router.get('/auth/me', summary='Текущий пользователь')
async def me(user: User = Depends(current_user)) -> dict:
    return _user(user)


@router.post('/auth/password', summary='Сменить свой пароль')
async def change_password(
    schema: PasswordSchema,
    user: User = Depends(current_user),
    auth: AuthService = Depends(resolve(AuthService)),
) -> dict:
    await auth.change_password(user, schema.password)
    return {'ok': True}


@router.get('/users', summary='Пользователи')
async def list_users(
    _: User = Depends(current_user),
    auth: AuthService = Depends(resolve(AuthService)),
) -> list[dict]:
    return [_user(u) for u in await auth.list_users()]


@router.post('/users', status_code=HTTPStatus.CREATED, summary='Добавить')
async def create_user(
    schema: CredentialsSchema,
    _: User = Depends(current_user),
    auth: AuthService = Depends(resolve(AuthService)),
) -> dict:
    return _user(await auth.create_user(schema.username, schema.password))


@router.delete('/users/{username}', summary='Удалить пользователя')
async def delete_user(
    username: str,
    _: User = Depends(current_user),
    auth: AuthService = Depends(resolve(AuthService)),
) -> dict:
    await auth.delete_user(username)
    return {'ok': True}
