import { useMemo, useState } from 'react'

import { api } from '../api'
import { Action, Alert, Tile, fmtDate, nf, useLoad } from '../components/ui'
import { FriendsReport, RankedFriend, Settings } from '../types'

const TIERS: Record<string, [string, string]> = {
  protected: ['good', 'защищён'],
  open_order: ['good', 'открытый заказ'],
  long_buyer: ['', 'давний покупатель'],
  buyer: ['', 'покупатель'],
  friend: ['', 'друг'],
  invite: ['warn', 'заявка'],
}

const RELATION = { friend: 'друг', invite_sent: 'исходящая заявка', invite_received: 'входящая заявка' }

export default function SteamPage() {
  const report = useLoad(() => api.get<FriendsReport>('/steam/friends'))
  const settings = useLoad(() => api.get<Settings>('/settings'))
  const removalOff = settings.data ? !settings.data.friends.allow_removal : false
  const [selected, setSelected] = useState<Set<string>>(new Set())
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

  function toggle(id: string) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  async function remove(ids: string[]) {
    const res = await api.post<{ steam_id: string; removed?: boolean; error?: string }[]>(
      '/steam/friends/remove',
      { steam_ids: ids },
    )
    const ok = res.filter((x) => x.removed).length
    const errors = res.filter((x) => x.error).map((x) => x.error)
    setResult(`Удалено: ${ok}.${errors.length ? ' Не удалось: ' + errors.join('; ') : ''}`)
    setSelected(new Set())
    await report.reload()
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Друзья Steam</h1>
          <div className="sub">
            Порядок важности: защищённые → с открытым заказом → давние покупатели → покупатели → друзья (по
            уровню) → заявки. Удаляются только снизу, и только после подтверждения.
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
      {removalOff ? (
        <Alert kind="warn">Удаление друзей отключено в «Настройки → Друзья». Список и кандидаты видны, но удалить никого нельзя.</Alert>
      ) : null}
      {refreshing ? (
        <Alert kind="warn">Загружаю друзей, имена и уровни из Steam. Первый раз — до полуминуты, дальше уровни берутся из кэша.</Alert>
      ) : null}
      <Alert kind="good">{result}</Alert>
      {r ? (
        <div className="tiles">
          <Tile k="Занято слотов" v={nf.format(r.used)} d="друзья + исходящие заявки" />
          <Tile k="Лимит" v={r.limit ? nf.format(r.limit) : '—'} d={r.own_level != null ? `уровень ${r.own_level}` : 'обновите из Steam'} />
          <Tile k="Держать свободными" v={nf.format(r.keep_free)} />
          <Tile k="Нужно освободить" v={nf.format(r.to_free)} d={`обновлено ${fmtDate(r.refreshed_at)}`} />
        </div>
      ) : null}
      {r && r.candidates.length ? (
        <div className="card stack">
          <h2>Кандидаты на удаление ({r.candidates.length})</h2>
          <FriendsTable rows={r.candidates} selected={selected} toggle={toggle} />
          <div className="row">
            <Action
              className="danger"
              disabled={removalOff}
              confirm={`Удалить из друзей ${r.candidates.length} чел.? Это действие в Steam, отменить его нельзя.`}
              onError={setError}
              onRun={() => remove(r.candidates.map((c) => c.friend.steam_id))}
            >
              Удалить всех кандидатов
            </Action>
          </div>
        </div>
      ) : null}
      <div className="card stack">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>Все по важности</h2>
          <div className="row">
            <input placeholder="Поиск по нику или id" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Поиск" />
            <Action
              className="danger"
              disabled={!selected.size || removalOff}
              confirm={`Удалить выбранных (${selected.size})? Это действие в Steam, отменить его нельзя.`}
              onError={setError}
              onRun={() => remove([...selected])}
            >
              Удалить выбранных ({selected.size})
            </Action>
          </div>
        </div>
        {rows.length ? (
          <FriendsTable rows={rows} selected={selected} toggle={toggle} withProtect onChanged={report.reload} />
        ) : (
          <div className="sub">Список пуст. Задайте ключ Steam Web API и Steam ID в настройках и нажмите «Обновить из Steam».</div>
        )}
      </div>
    </>
  )
}

function FriendsTable(props: {
  rows: RankedFriend[]
  selected: Set<string>
  toggle: (id: string) => void
  withProtect?: boolean
  onChanged?: () => Promise<void>
}) {
  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th />
            <th className="num">#</th>
            <th>Steam</th>
            <th>Важность</th>
            <th>Покупатель FunPay</th>
            <th className="num">Уровень</th>
            <th>В друзьях с</th>
            <th>Последний заказ</th>
            {props.withProtect ? <th /> : null}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((r) => {
            const [kind, label] = TIERS[r.tier] ?? ['', r.tier]
            const id = r.friend.steam_id
            return (
              <tr key={id} className={props.selected.has(id) ? 'sel' : ''}>
                <td>
                  <input
                    type="checkbox"
                    disabled={!r.removable}
                    checked={props.selected.has(id)}
                    onChange={() => props.toggle(id)}
                    aria-label={`Выбрать ${r.friend.name || id}`}
                  />
                </td>
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
                <td className="num">{r.friend.level ?? '—'}</td>
                <td>{fmtDate(r.friend.friend_since)}</td>
                <td>{fmtDate(r.last_order_at)}</td>
                {props.withProtect ? (
                  <td>
                    {r.tier === 'protected' ? (
                      <Action
                        onRun={async () => {
                          await api.del(`/steam/protected/${id}`)
                          await props.onChanged?.()
                        }}
                      >
                        Снять защиту
                      </Action>
                    ) : (
                      <Action
                        onRun={async () => {
                          const note = window.prompt('Кто это? (заметка, необязательно)') ?? ''
                          await api.post('/steam/protected', { steam_id: id, note })
                          await props.onChanged?.()
                        }}
                      >
                        Защитить
                      </Action>
                    )}
                  </td>
                ) : null}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
