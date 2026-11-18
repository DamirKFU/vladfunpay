import { useMemo, useState } from 'react'

import { api } from '../api'
import { FriendsReport, RankedFriend } from '../types'
import { Action, Alert, Tile, fmtDate, nf, useLoad } from '../components/ui'

const TIERS: Record<string, [string, string]> = {
  protected: ['good', 'закреплён'],
  open_order: ['good', 'открытый заказ'],
  buyer: ['', 'покупатель'],
  friend: ['', 'друг'],
  invite: ['warn', 'заявка'],
}

const RELATION = { friend: 'друг', invite_sent: 'исходящая заявка', invite_received: 'входящая заявка' }

export default function SteamPage() {
  const report = useLoad(() => api.get<FriendsReport>('/steam/friends'))
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const r = report.data
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return (r?.ranked ?? []).filter(
      (f) =>
        !q ||
        f.friend.name.toLowerCase().includes(q) ||
        f.buyer_name.toLowerCase().includes(q) ||
        f.friend.steam_id.includes(q),
    )
  }, [r, filter])

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Друзья Steam</h1>
          <div className="sub">
            Сначала закреплённые и с открытым заказом. Дальше по дате последней покупки и добавления в друзья. Заявки внизу.
          </div>
        </div>
        <div className="row">
          <button
            className="primary"
            disabled={refreshing}
            onClick={async () => {
              setError('')
              setRefreshing(true)
              const started = Date.now()
              try {
                report.setData(await api.post<FriendsReport>('/steam/friends/refresh'))
                setResult(`Обновлено за ${Math.round((Date.now() - started) / 1000)} с`)
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
              } finally {
                setRefreshing(false)
              }
            }}
          >
            {refreshing ? 'Обновляю из Steam…' : 'Обновить из Steam'}
          </button>
        </div>
      </div>
      <Alert kind="bad">{error || report.error}</Alert>
      {refreshing ? (
        <Alert kind="warn">Загружаю список друзей и заявки из Steam.</Alert>
      ) : null}
      <Alert kind="good">{result}</Alert>
      {r ? (
        <div className="tiles">
          <Tile k="Занято слотов" v={nf.format(r.used)} d="друзья + исходящие заявки" />
          <Tile k="Лимит" v={r.limit ? nf.format(r.limit) : '—'} d={r.own_level != null ? `уровень ${r.own_level}` : 'обновите из Steam'} />
          <Tile k="Свободно" v={r.limit == null ? '—' : nf.format(Math.max(0, r.limit - r.used))} d={`обновлено ${fmtDate(r.refreshed_at)}`} />
        </div>
      ) : null}
      <div className="card stack">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>Все по важности</h2>
          <div className="row">
            <input placeholder="Поиск по нику или id" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Поиск" />
          </div>
        </div>
        {rows.length ? (
          <FriendsTable rows={rows} onChanged={report.reload} />
        ) : (
          <div className="sub">Список пуст. Задайте ключ Steam Web API и Steam ID в настройках и нажмите «Обновить из Steam».</div>
        )}
      </div>
    </>
  )
}

function FriendsTable(props: {
  rows: RankedFriend[]
  onChanged?: () => Promise<void>
}) {
  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>Steam</th>
            <th>Важность</th>
            <th>Покупатель FunPay</th>
            <th>В друзьях с</th>
            <th>Последний заказ</th>
            <th scope="col">Закрепление</th>
          </tr>
        </thead>
        <tbody>
          {props.rows.map((r) => {
            const [kind, label] = TIERS[r.tier] ?? ['', r.tier]
            const id = r.friend.steam_id
            return (
              <tr key={id}>
                <td className="num">{r.rank}</td>
                <td>
                  <a href={`https://steamcommunity.com/profiles/${id}`} target="_blank" rel="noopener noreferrer">
                    {r.friend.name || id}
                  </a>
                  <div className="sub">{RELATION[r.friend.relationship]}</div>
                </td>
                <td>
                  <span className={`badge ${kind}`}>{label}</span>
                </td>
                <td>
                  {r.buyer_name || '—'}
                  {r.orders ? <div className="sub">заказов: {r.orders}</div> : null}
                </td>
                <td>{fmtDate(r.friend.friend_since)}</td>
                <td>{fmtDate(r.last_order_at)}</td>
                <td>
                    {r.tier === 'protected' ? (
                      <Action
                        onRun={async () => {
                          await api.del(`/steam/protected/${id}`)
                          await props.onChanged?.()
                        }}
                      >
                        Открепить
                      </Action>
                    ) : (
                      <Action
                        onRun={async () => {
                          const note = window.prompt('Кто это? (заметка, необязательно)') ?? ''
                          await api.post('/steam/protected', { steam_id: id, note })
                          await props.onChanged?.()
                        }}
                      >
                        Закрепить
                      </Action>
                    )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
