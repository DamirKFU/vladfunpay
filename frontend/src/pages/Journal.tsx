import { useState } from 'react'

import { api } from '../api'
import { StatusBadge, StatusChips, StatusDef } from '../components/JournalParts'
import { Action, Alert, fmtDate, useLoad, usePolling } from '../components/ui'
import { SalesSnapshot } from '../types'

const STATUSES: StatusDef[] = [
  { value: 'paid', label: 'Оплачен', kind: 'warn' },
  { value: 'closed', label: 'Закрыт', kind: 'good' },
  { value: 'refunded', label: 'Возврат', kind: 'bad' },
]
const formatPrice = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

export default function JournalPage() {
  const [statuses, setStatuses] = useState<string[]>(['paid'])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const journal = useLoad(() => api.get<SalesSnapshot>('/journal/orders'))
  usePolling(() => void journal.reload(), 10000)

  const query = search.trim().toLowerCase()
  const { data } = journal
  const orders = data?.items ?? []
  const counts: Record<string, number> = {}
  for (const order of orders) counts[order.status] = (counts[order.status] ?? 0) + 1
  const items = orders.filter((order) => {
    const matchesStatus = !statuses.length || statuses.includes(order.status)
    const matchesSearch = [order.order_id, order.title, order.buyer_name].some((value) =>
      value.toLowerCase().includes(query),
    )
    return matchesStatus && matchesSearch
  })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Заказы</h1>
          <div className="sub">Все открытые заказы и последние продажи FunPay.</div>
        </div>
        <Action
          onError={setError}
          disabled={data?.refreshing}
          onRun={async () => {
            setError('')
            await api.post('/journal/orders/funpay/sync')
            await journal.reload()
          }}
        >
          Обновить с FunPay
        </Action>
      </div>
      <Alert kind="bad">{error || journal.error || data?.error}</Alert>
      <div className="card stack">
        <div className="sub" role="status">
          {data?.refreshing ? 'Загружаем заказы с FunPay. ' : ''}
          {data?.refreshed_at ? 'Обновлено ' + fmtDate(data.refreshed_at) : 'Первая синхронизация ещё не завершена.'}
          {data ? ' · Автообновление каждые ' + data.interval_seconds / 60 + ' мин.' : ''}
        </div>
        <input
          type="search"
          placeholder="Номер, товар или покупатель"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Поиск по номеру, товару или покупателю"
        />
        <StatusChips statuses={STATUSES} selected={statuses} counts={counts} onChange={setStatuses} />
      </div>
      <div className="card tbl-wrap">
        {items.length ? (
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Заказ</th>
                <th>Товар</th>
                <th>Покупатель</th>
                <th className="num">Сумма</th>
                <th>Статус FunPay</th>
              </tr>
            </thead>
            <tbody>
              {items.map((order) => (
                <tr key={order.order_id}>
                  <td>{order.date_text || '—'}</td>
                  <td>
                    <a
                      href={'https://funpay.com/orders/' + encodeURIComponent(order.order_id) + '/'}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      #{order.order_id}
                    </a>
                  </td>
                  <td>{order.title}</td>
                  <td>{order.buyer_name}</td>
                  <td className="num">{formatPrice.format(order.price)} {order.currency}</td>
                  <td>
                    <StatusBadge def={STATUSES.find(({ value }) => value === order.status) ?? {
                      value: order.status, label: order.status, kind: '',
                    }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="sub">
            {journal.loading
              ? 'Загружаем список заказов…'
              : data?.refreshed_at
                ? 'По этим фильтрам заказов нет.'
                : 'Сохраните подключение к FunPay в настройках и обновите список.'}
          </div>
        )}
      </div>
    </>
  )
}
