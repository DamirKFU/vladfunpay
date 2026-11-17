import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from punq import Container
from pymongo.asynchronous.database import AsyncDatabase

from app.application.deps import get_container
from app.application.errors import install_logging_and_errors
from app.application.routes import admin, auth, bot, lots, services, steam
from app.container import init_container
from app.core.log_sink import (
    QueueLogHandler,
    flush_forever,
    setup_stdout_logging,
)
from app.db.mongo import ensure_indexes
from app.repositories.base import BaseLogRepository
from app.settings import Config
from app.workers.runtime import Workers

log = logging.getLogger('app')


def create_app(
    container_factory: Callable[[], Container] = init_container,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        container = container_factory()
        config: Config = container.resolve(Config)
        setup_stdout_logging(config.log_level)
        handler = QueueLogHandler(asyncio.get_running_loop())
        logging.getLogger().addHandler(handler)
        tasks = [
            asyncio.create_task(
                flush_forever(handler, container.resolve(BaseLogRepository)),
            ),
        ]
        workers: Workers = container.resolve(Workers)
        if config.run_workers:
            await ensure_indexes(
                container.resolve(AsyncDatabase),
                config.log_ttl_days,
            )
            workers.start()
        log.info('Сервер запущен')
        try:
            yield
        finally:
            await workers.stop()
            for task in tasks:
                task.cancel()
            logging.getLogger().removeHandler(handler)

    app = FastAPI(
        title='FunPay Seller',
        description='Продажи FunPay, бот с ИИ, друзья Steam.',
        lifespan=lifespan,
        docs_url='/api/docs',
        openapi_url='/api/openapi.json',
    )
    app.dependency_overrides[get_container] = container_factory

    install_logging_and_errors(app)

    @app.get('/api/health', tags=['health'])
    async def health() -> dict:
        return {'ok': True}

    for module in (auth, admin, bot, steam, services, lots):
        app.include_router(module.router, prefix='/api')
    return app


app = create_app()
