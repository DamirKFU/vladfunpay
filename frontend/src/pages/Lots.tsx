import { Fragment, useState } from 'react'

import { api } from '../api'
import { Action, Alert, fmtDate, rub, useLoad } from '../components/ui'
import { Channel, LotRecord, ProductType, Settings } from '../types'

const ASSIGNED: Record<string, [string, string]> = {
  manual: ['good', 'вручную'],
  keywords: ['', 'по словам'],
  ai: ['', 'ИИ'],
  default: ['warn', 'по умолчанию'],
  '': ['warn', 'не определён'],
}

type Account = { login: string; password: string; email: string; email_password: string; note: string }
const EMPTY: Account = { login: '', password: '', email: '', email_password: '', note: '' }

export default function LotsPage() {
  const [channel, setChannel] = useState<Channel>('funpay')
  const lots = useLoad(() => api.get<LotRecord[]>(`/lots/${channel}`), [channel])
  const settings = useLoad(() => api.get<Settings>('/settings'))
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const types = settings.data?.catalog.types ?? []
  const typeOf = (id: string) => types.find((t) => t.id === id)
  const openLot = (lots.data ?? []).find((l) => l.lot_id === open)

  async function setType(lot: LotRecord, typeId: string) {
    setError('')
    const saved = await api.put<LotRecord>(`/lots/${channel}/${lot.lot_id}/type`, {
      type_id: typeId || null,
    })
    lots.setData((lots.data ?? []).map((l) => (l.lot_id === saved.lot_id ? saved : l)))
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Лоты</h1>
          <div className="sub">
            Карточки лотов и их тип товара. Тип бот берёт для заказа по названию лота. Новые лоты типизируются сами
            (слова-ключи → ИИ по описанию → по умолчанию); выбор вручную не перетирается.
          </div>
        </div>
        <div className="row">
          <div className="tabs" style={{ margin: 0, border: 0 }}>
            {(['funpay', 'sandbox'] as Channel[]).map((c) => (
              <button key={c} className={c === channel ? 'on' : ''} onClick={() => setChannel(c)}>
                {c === 'funpay' ? 'FunPay' : 'Песочница'}
              </button>
            ))}
          </div>
          <Action
            className="primary"
            onError={setError}
            onRun={async () => {
              setError('')
              lots.setData(await api.post<LotRecord[]>(`/lots/${channel}/sync`))
              setOk('Лоты обновлены')
            }}
          >
            Синхронизировать лоты
          </Action>
        </div>
      </div>
      <Alert kind="bad">{error || lots.error}</Alert>
      <Alert kind="good">{ok}</Alert>
      <div className="card tbl-wrap">
        {lots.data && lots.data.length ? (
          <table>
            <thead>
              <tr>
                <th>Лот</th>
                <th>Тип товара</th>
                <th>Как определён</th>
                <th className="num">Цена</th>
                <th className="num">В наличии</th>
                <th>Обновлён</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lots.data.map((lot) => {
                const [kind, label] = ASSIGNED[lot.assigned_by] ?? ['', lot.assigned_by]
                const ptype = typeOf(lot.type_id)
                return (
                  <Fragment key={lot.lot_id}>
                    <tr>
                      <td style={{ minWidth: 220, maxWidth: 420 }}>
                        <b>{lot.title}</b>
                        {lot.description ? (
                          <div className="sub" style={{ whiteSpace: 'pre-wrap' }}>
                            {lot.description.length > 180 && open !== lot.lot_id
                              ? lot.description.slice(0, 180) + '…'
                              : lot.description}
                          </div>
                        ) : (
                          <div className="sub">описания нет</div>
                        )}
                      </td>
                      <td>
                        <select value={lot.assigned_by === 'manual' ? lot.type_id : ''} onChange={(e) => void setType(lot, e.target.value).catch((err) => setError(String(err.message ?? err)))} aria-label={`Тип лота ${lot.title}`}>
                          <option value="">авто: {ptype?.name ?? '—'}</option>
                          {types.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <span className={`badge ${kind}`}>{label}</span>
                      </td>
                      <td className="num">{rub(lot.price)}</td>
                      <td className="num">
                        {lot.amount ?? '—'}
                        {lot.auto_delivery ? <div className="sub">автовыдача</div> : null}
                      </td>
                      <td>{fmtDate(lot.updated_at)}</td>
                      <td>
                        <button onClick={() => setOpen(open === lot.lot_id ? null : lot.lot_id)}>
                          {open === lot.lot_id ? 'Свернуть' : ptype?.kind === 'account' ? 'Аккаунты' : 'Подробнее'}
                        </button>
                      </td>
                    </tr>
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className="sub">
            Лотов нет. Нажмите «Синхронизировать лоты»
            {channel === 'sandbox' ? ' или добавьте лоты в песочнице' : ' (нужен golden_key FunPay)'}.
          </div>
        )}
      </div>
      {openLot ? (
        <div className="card stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h2>{openLot.title}</h2>
            <button onClick={() => setOpen(null)}>Закрыть</button>
          </div>
          {typeOf(openLot.type_id)?.kind === 'account' ? (
            <AccountsForm
              channel={channel}
              lot={openLot}
              onSaved={(saved) => {
                lots.setData((lots.data ?? []).map((l) => (l.lot_id === saved.lot_id ? saved : l)))
                setOk(`Аккаунты добавлены в автовыдачу «${saved.title}», в наличии ${saved.amount}`)
              }}
            />
          ) : (
            <TypeInfo ptype={typeOf(openLot.type_id)} />
          )}
        </div>
      ) : null}
    </>
  )
}

function TypeInfo({ ptype }: { ptype?: ProductType }) {
  if (!ptype) return <div className="sub">Тип не найден в настройках.</div>
  return (
    <div className="stack sub">
      <div>
        <b>{ptype.name}</b> · {ptype.kind}
        {ptype.kind === 'gift' ? ` · ${ptype.friend_days} дн. дружбы, ${ptype.per_day} подарков в день` : ''}
      </div>
      <div style={{ whiteSpace: 'pre-wrap' }}>{ptype.instructions || 'Инструкции для ИИ не заданы.'}</div>
    </div>
  )
}

function AccountsForm(props: { channel: Channel; lot: LotRecord; onSaved: (lot: LotRecord) => void }) {
  const [rows, setRows] = useState<Account[]>([{ ...EMPTY }])
  const [error, setError] = useState('')
  const valid = rows.every((r) => r.login.trim() && r.password.trim())
  const field = (i: number, key: keyof Account, label: string, type = 'text') => (
    <input
      type={type}
      autoComplete="off"
      placeholder={label}
      aria-label={label}
      value={rows[i][key]}
      onChange={(e) => setRows(rows.map((r, j) => (j === i ? { ...r, [key]: e.target.value } : r)))}
      style={{ minWidth: 120, flex: 1 }}
    />
  )
  return (
    <div className="stack">
      <Alert kind="warn">
        Данные сразу уходят в автовыдачу этого лота на FunPay (по одному аккаунту на строку) и у нас не сохраняются —
        ни в базе, ни в логах. Покупатель получает их от FunPay сразу после оплаты.
      </Alert>
      <Alert kind="bad">{error}</Alert>
      {rows.map((_, i) => (
        <div key={i} className="row">
          {field(i, 'login', 'Логин Steam')}
          {field(i, 'password', 'Пароль Steam', 'password')}
          {field(i, 'email', 'Почта')}
          {field(i, 'email_password', 'Пароль почты', 'password')}
          {field(i, 'note', 'Примечание')}
          <button className="danger" disabled={rows.length === 1} onClick={() => setRows(rows.filter((__, j) => j !== i))}>
            ✕
          </button>
        </div>
      ))}
      <div className="row">
        <button onClick={() => setRows([...rows, { ...EMPTY }])}>Ещё аккаунт</button>
        <Action
          className="primary"
          disabled={!valid}
          confirm={`Добавить ${rows.length} акк. в автовыдачу «${props.lot.title}»?`}
          onError={setError}
          onRun={async () => {
            setError('')
            const saved = await api.post<LotRecord>(`/lots/${props.channel}/${props.lot.lot_id}/accounts`, {
              accounts: rows,
            })
            setRows([{ ...EMPTY }])
            props.onSaved(saved)
          }}
        >
          Отправить в автовыдачу
        </Action>
      </div>
    </div>
  )
}
