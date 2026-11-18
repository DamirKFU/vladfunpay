"""Просмотр заказов FunPay и обновление локального снимка."""

from fastapi import APIRouter, Depends

from app.application.deps import current_user, resolve
from app.usecases.journal import OrderJournalService

router = APIRouter(dependencies=[Depends(current_user)])


@router.get('/journal/orders', tags=['journal'], summary='Заказы FunPay')
async def orders_journal(
    service: OrderJournalService = Depends(resolve(OrderJournalService)),
) -> dict:
    return await service.view()


@router.post(
    '/journal/orders/funpay/sync',
    tags=['journal'],
    summary='Обновить список заказов с FunPay',
)
async def orders_journal_sync(
    service: OrderJournalService = Depends(resolve(OrderJournalService)),
) -> dict:
    await service.sync()
    return await service.view()
