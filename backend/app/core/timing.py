import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter


@asynccontextmanager
async def logged_call(
    logger: logging.Logger,
    what: str,
    level: int = logging.INFO,
) -> AsyncIterator[None]:
    """Пишет в лог каждый внешний вызов: успех с длительностью или ошибку."""
    start = perf_counter()
    try:
        yield
    except Exception as e:
        ms = (perf_counter() - start) * 1000
        logger.warning('%s: ошибка за %.0f мс: %s', what, ms, e)
        raise
    ms = (perf_counter() - start) * 1000
    logger.log(level, '%s: ок за %.0f мс', what, ms)
