"""Журнал запросов API и обработка ошибок с записью в лог."""

import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.deps import client_key
from app.integrations.provider import NotConfiguredError
from app.usecases.errors import UseCaseError

api_log = logging.getLogger('api')


def install_logging_and_errors(app: FastAPI) -> None:
    @app.middleware('http')
    async def log_requests(request: Request, call_next):  # noqa: ANN001
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            api_log.exception(
                'API %s %s: необработанная ошибка',
                request.method,
                request.url.path,
            )
            return JSONResponse(
                {'detail': 'внутренняя ошибка сервера, подробности в логах'},
                status_code=500,
            )
        path = request.url.path
        if path.startswith('/api'):
            status = response.status_code
            quiet = request.method == 'GET' and _is_polling(path)
            if status >= 500:
                level = logging.ERROR
            elif status >= 400:
                level = logging.WARNING
            elif quiet:
                return response
            else:
                level = logging.INFO
            api_log.log(
                level,
                'API %s %s → %d (%.0f мс)',
                request.method,
                path,
                status,
                (perf_counter() - start) * 1000,
                extra={'client': client_key(request)},
            )
        return response

    @app.exception_handler(UseCaseError)
    async def usecase_error(
        request: Request,
        exc: UseCaseError,
    ) -> JSONResponse:
        api_log.warning(
            '%s %s: %s',
            request.method,
            request.url.path,
            exc.message,
        )
        return JSONResponse(
            {'detail': exc.message},
            status_code=exc.status_code,
        )

    @app.exception_handler(NotConfiguredError)
    async def not_configured(request: Request, exc: Exception) -> JSONResponse:
        api_log.warning('%s %s: %s', request.method, request.url.path, exc)
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def bad_request(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        api_log.warning(
            '%s %s: неверные данные %s',
            request.method,
            request.url.path,
            [e.get('loc') for e in exc.errors()],
        )
        return JSONResponse(
            {'detail': jsonable_encoder(exc.errors())},
            status_code=422,
        )


# GET-запросы, которые фронт шлёт каждые несколько секунд: в лог попадают
# только при ошибке, иначе они забьют весь журнал.
POLLING_PATHS = (
    '/api/health',
    '/api/logs',
    '/api/logs/sources',
    '/api/sync/runs',
    '/api/orders/summary',
    '/api/funpay/raise',
    '/api/journal/orders',
)
POLLING_PREFIXES = ()


def _is_polling(path: str) -> bool:
    return path in POLLING_PATHS or path.startswith(POLLING_PREFIXES)
