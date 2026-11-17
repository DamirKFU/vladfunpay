from fastapi import Depends, Header, Request
from punq import Container

from app.container import init_container
from app.core import messages
from app.models.domain import User
from app.usecases.auth import AuthService
from app.usecases.errors import AuthError


def get_container() -> Container:
    return init_container()


def resolve(cls: type):
    """Depends(resolve(SomeService)) — сервис из контейнера."""

    def dependency(container: Container = Depends(get_container)):
        return container.resolve(cls)

    return dependency


async def current_user(
    authorization: str = Header(default=''),
    auth: AuthService = Depends(resolve(AuthService)),
) -> User:
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise AuthError(messages.AUTH_TOKEN_INVALID)
    return await auth.current_user(token)


def client_key(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'
