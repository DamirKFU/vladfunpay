"""Настройки, синхронизация продаж, отчёт, логи и выгрузка базы."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response

from app.application.deps import current_user, resolve
from app.application.schemas import SettingsPatchSchema
from app.repositories.base import BaseOrderRepository
from app.usecases.data import DatabaseExportService, LogService, ReportService
from app.usecases.settings import SettingsService
from app.usecases.sync import SyncService

router = APIRouter(dependencies=[Depends(current_user)])
MSK = ZoneInfo('Europe/Moscow')


def _attachment(name: str, ext: str) -> dict[str, str]:
    stamp = datetime.now(MSK).strftime('%Y%m%d-%H%M')
    filename = f'{name}-{stamp}.{ext}'
    return {'Content-Disposition': f'attachment; filename="{filename}"'}


@router.get('/settings', tags=['settings'], summary='Настройки проекта')
async def get_settings(
    service: SettingsService = Depends(resolve(SettingsService)),
) -> dict:
    return await service.public()


@router.patch('/settings', tags=['settings'], summary='Изменить настройки')
async def patch_settings(
    schema: SettingsPatchSchema,
    service: SettingsService = Depends(resolve(SettingsService)),
) -> dict:
    return await service.update(schema.patch())


@router.post('/sync', tags=['sales'], summary='Синхронизировать продажи')
async def start_sync(
    service: SyncService = Depends(resolve(SyncService)),
):
    return await service.start()


@router.get('/sync/runs', tags=['sales'], summary='История синхронизаций')
async def sync_runs(
    service: SyncService = Depends(resolve(SyncService)),
):
    return await service.history()


@router.get('/orders/summary', tags=['sales'], summary='Сколько заказов')
async def orders_summary(
    orders: BaseOrderRepository = Depends(resolve(BaseOrderRepository)),
) -> dict:
    return {
        'count': await orders.count(),
        'last_paid_at': await orders.max_paid_at(),
    }


@router.get(
    '/orders/report',
    tags=['sales'],
    summary='HTML-отчёт по продажам',
    response_class=HTMLResponse,
)
async def orders_report(
    service: ReportService = Depends(resolve(ReportService)),
) -> str:
    return await service.html()


@router.get('/logs', tags=['logs'], summary='Логи')
async def list_logs(
    level: str | None = None,
    source: str | None = None,
    search: str | None = None,
    hours: int | None = Query(default=None, ge=1, le=24 * 90),
    limit: int = Query(default=300, ge=1, le=2000),
    service: LogService = Depends(resolve(LogService)),
):
    return await service.query(level, source, search, hours, limit)


@router.get('/logs/sources', tags=['logs'], summary='Источники логов')
async def log_sources(
    service: LogService = Depends(resolve(LogService)),
) -> list[str]:
    return await service.sources()


@router.get('/logs/export', tags=['logs'], summary='Скачать логи (JSONL)')
async def export_logs(
    level: str | None = None,
    source: str | None = None,
    hours: int | None = Query(default=None, ge=1, le=24 * 90),
    service: LogService = Depends(resolve(LogService)),
) -> Response:
    data = await service.export(level, source, hours)
    return Response(
        data,
        media_type='application/x-ndjson',
        headers=_attachment('logs', 'jsonl'),
    )


@router.get('/data/export', tags=['data'], summary='Выгрузить базу (ZIP)')
async def export_database(
    service: DatabaseExportService = Depends(resolve(DatabaseExportService)),
) -> Response:
    return Response(
        await service.export_bytes(),
        media_type='application/zip',
        headers=_attachment('funpay-db', 'zip'),
    )
