import { useEffect, useState } from 'react'

import { api } from '../api'
import { Action, Alert, Tile, fmtDate, nf, useLoad, usePolling } from '../components/ui'
import { SyncRun } from '../types'

type Summary = { count: number; last_paid_at: string | null }

export default function Dashboard() {
  const summary = useLoad(() => api.get<Summary>('/orders/summary'))
  const runs = useLoad(() => api.get<SyncRun[]>('/sync/runs'))
  const report = useLoad(() => api.text('/orders/report'))
  const [error, setError] = useState('')
  const last = runs.data?.[0]
  const running = last?.status === 'running'
  const lastSuccessId = runs.data?.find((run) => run.status === 'done')?.id
  const { reload: reloadSummary } = summary
  const { reload: reloadReport } = report

  usePolling(() => void runs.reload(), running ? 3000 : 15000)
  useEffect(() => {
    if (lastSuccessId) {
      void reloadSummary()
      void reloadReport()
    }
  }, [lastSuccessId, reloadSummary, reloadReport])

  const firstSync = (summary.data?.count ?? 0) === 0

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Продажи</h1>
          <div className="sub">
            Первая выгрузка за всё время, затем синхронизация продаж примерно раз в час.
          </div>
        </div>
        <div className="row">
          <Action
            className="primary"
            disabled={running}
            onError={setError}
            onRun={async () => {
              setError('')
              await api.post('/sync')
              await runs.reload()
            }}
          >
            {running ? 'Синхронизация…' : firstSync ? 'Загрузить всё с FunPay' : 'Синхронизировать'}
          </Action>
          <Action onRun={() => api.download('/data/export', 'funpay-db.zip')}>Выгрузить базу (ZIP)</Action>
        </div>
      </div>
      <Alert kind="bad">{error || summary.error || runs.error || report.error}</Alert>
      <div className="tiles">
        <Tile k="Заказов в базе" v={summary.data ? nf.format(summary.data.count) : '—'} />
        <Tile k="Последняя оплата" v={fmtDate(summary.data?.last_paid_at)} />
        <Tile
          k="Последняя синхронизация"
          v={last ? <SyncBadge run={last} /> : 'не было'}
          d={
            last
              ? `${last.date_from ?? 'за всё время'} — ${last.date_to}${last.message ? ' · ' + last.message : ''}`
              : undefined
          }
        />
      </div>
      {report.data && (summary.data?.count ?? 0) > 0 ? (
        <iframe className="report" title="Отчёт по продажам" srcDoc={report.data} sandbox="allow-scripts" />
      ) : (
        <div className="card sub">
          Заказов пока нет. Заполните golden_key в настройках и нажмите «Загрузить всё с FunPay».
        </div>
      )}
      {runs.data && runs.data.length > 0 ? (
        <div className="card">
          <h2>История синхронизаций</h2>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Начата</th>
                  <th>Период</th>
                  <th>Статус</th>
                  <th className="num">Получено</th>
                  <th>Сообщение</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDate(r.started_at)}</td>
                    <td>
                      {r.date_from ?? 'всё время'} — {r.date_to}
                    </td>
                    <td>
                      <SyncBadge run={r} />
                    </td>
                    <td className="num">{nf.format(r.fetched)}</td>
                    <td className="wrap">{r.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </>
  )
}

function SyncBadge({ run }: { run: SyncRun }) {
  const map = {
    running: ['warn', 'идёт'],
    done: ['good', 'готово'],
    error: ['bad', 'ошибка'],
  } as const
  const [kind, label] = map[run.status]
  return <span className={`badge ${kind}`}>{label}</span>
}
