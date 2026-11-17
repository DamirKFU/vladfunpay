import { useState } from 'react'

import { api } from '../api'
import { Action, Alert, fmtDate, useLoad, usePolling } from '../components/ui'
import { LogEntry } from '../types'

const LEVEL_KIND: Record<string, string> = { ERROR: 'bad', CRITICAL: 'bad', WARNING: 'warn', INFO: '', DEBUG: '' }

export default function LogsPage() {
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [search, setSearch] = useState('')
  const [hours, setHours] = useState('24')
  const [live, setLive] = useState(true)
  const sources = useLoad(() => api.get<string[]>('/logs/sources'))
  const params = new URLSearchParams()
  if (level) params.set('level', level)
  if (source) params.set('source', source)
  if (search) params.set('search', search)
  if (hours) params.set('hours', hours)
  const query = params.toString()
  const logs = useLoad(() => api.get<LogEntry[]>(`/logs?${query}`), [query])
  usePolling(() => void logs.reload(), 5000, live)

  const exportParams = new URLSearchParams(params)
  exportParams.delete('search')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Логи</h1>
          <div className="sub">Хранятся в базе 30 дней. Ключи и cookie в логах вырезаются.</div>
        </div>
        <Action onRun={() => api.download(`/logs/export?${exportParams}`, 'logs.jsonl')}>Скачать логи (JSONL)</Action>
      </div>
      <div className="card row">
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Уровень">
          <option value="">Все уровни</option>
          <option>ERROR</option>
          <option>WARNING</option>
          <option>INFO</option>
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)} aria-label="Источник">
          <option value="">Все источники</option>
          {(sources.data ?? []).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select value={hours} onChange={(e) => setHours(e.target.value)} aria-label="Период">
          <option value="1">За час</option>
          <option value="24">За сутки</option>
          <option value="168">За неделю</option>
          <option value="">Всё время</option>
        </select>
        <input type="search" placeholder="Поиск по тексту" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Поиск" />
        <label className="check">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          обновлять
        </label>
      </div>
      <Alert kind="bad">{logs.error}</Alert>
      <div className="card tbl-wrap">
        {logs.data && logs.data.length ? (
          <table>
            <thead>
              <tr>
                <th>Время</th>
                <th>Уровень</th>
                <th>Источник</th>
                <th>Сообщение</th>
              </tr>
            </thead>
            <tbody>
              {logs.data.map((e, i) => (
                <tr key={i}>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(e.ts)}</td>
                  <td>
                    <span className={`badge ${LEVEL_KIND[e.level] ?? ''}`}>{e.level}</span>
                  </td>
                  <td>{e.source}</td>
                  <td className="wrap">
                    {e.message}
                    {Object.keys(e.context).length ? <div className="sub">{JSON.stringify(e.context)}</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="sub">Записей нет.</div>
        )}
      </div>
    </>
  )
}
