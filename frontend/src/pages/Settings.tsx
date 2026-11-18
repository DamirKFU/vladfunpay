import { ReactNode, useEffect, useState } from 'react'

import { api, errorText } from '../api'
import { Action, Alert, Field, fmtDate, useLoad } from '../components/ui'
import { RaiseStatus, Secret, Settings, User } from '../types'

const TABS = ['FunPay', 'Steam', 'Друзья', 'Пользователи', 'Данные'] as const
type Tab = (typeof TABS)[number]

export default function SettingsPage() {
  const loaded = useLoad(() => api.get<Settings>('/settings'))
  const [tab, setTab] = useState<Tab>('FunPay')
  const [draft, setDraft] = useState<Settings | null>(null)
  const [secrets, setSecrets] = useState<Record<string, string | null>>({})
  const [msg, setMsg] = useState<{ kind: 'good' | 'bad'; text: string } | null>(null)

  useEffect(() => {
    if (loaded.data) setDraft(structuredClone(loaded.data))
  }, [loaded.data])

  if (!draft) return <Alert kind="bad">{loaded.error}</Alert>

  function set<S extends keyof Settings>(section: S, patch: Partial<Settings[S]>) {
    setDraft((d) => (d ? { ...d, [section]: { ...d[section], ...patch } } : d))
  }

  async function save(section: keyof Settings) {
    const body: Record<string, unknown> = { ...draft![section] }
    for (const [key, value] of Object.entries(body)) {
      if (value && typeof value === 'object' && 'is_set' in (value as object)) delete body[key]
    }
    for (const [path, value] of Object.entries(secrets)) {
      const [sec, name] = path.split('.')
      if (sec === section) body[name] = value
    }
    try {
      const saved = await api.patch<Settings>('/settings', { [section]: body })
      loaded.setData(saved)
      setSecrets((s) => Object.fromEntries(Object.entries(s).filter(([k]) => !k.startsWith(section + '.'))))
      setMsg({ kind: 'good', text: 'Сохранено' })
    } catch (e) {
      setMsg({ kind: 'bad', text: errorText(e) })
    }
  }

  const secret = (path: string, label: string, current: Secret, hint?: ReactNode) => (
    <SecretField
      label={label}
      current={current}
      hint={hint}
      value={secrets[path]}
      onChange={(v) => setSecrets({ ...secrets, [path]: v })}
    />
  )

  const saveButton = (section: keyof Settings) => (
    <div className="row">
      <Action className="primary" onRun={() => save(section)}>
        Сохранить
      </Action>
    </div>
  )

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Настройки</h1>
          <div className="sub">Ключи хранятся в базе в зашифрованном виде и не показываются после сохранения.</div>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={t === tab} className={t === tab ? 'on' : ''} onClick={() => { setTab(t); setMsg(null) }}>
            {t}
          </button>
        ))}
      </div>
      {msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : null}

      {tab === 'FunPay' ? (
        <div className="card stack">
          <p className="sub">
            Вход без логина и пароля: cookie <b>golden_key</b> из браузера (DevTools → Application → Cookies →
            funpay.com). User-Agent — того же браузера, чтобы сессия выглядела одинаково.
          </p>
          <div className="fields">
            {secret('funpay.golden_key', 'golden_key', draft.funpay.golden_key)}
            <Field label="User-Agent">
              <input value={draft.funpay.user_agent} onChange={(e) => set('funpay', { user_agent: e.target.value })} />
            </Field>
          </div>
          <h3>Автоподнятие лотов</h3>
          <label className="check">
            <input type="checkbox" checked={draft.funpay.auto_raise} onChange={(e) => set('funpay', { auto_raise: e.target.checked })} />
            Поднимать лоты автоматически (как кнопка «Поднять предложения» на FunPay)
          </label>
          <Field label="Категории (игры) для поднятия" hint="ID игры FunPay через запятую, например 41 — Dota 2. Пусто — из синхронизированных продаж.">
            <input
              value={draft.funpay.raise_categories.join(', ')}
              onChange={(e) =>
                set('funpay', { raise_categories: e.target.value.split(/[ ,]+/).map(Number).filter((n) => n > 0) })
              }
            />
          </Field>
          {saveButton('funpay')}
          <RaiseStatusBlock />
        </div>
      ) : null}

      {tab === 'Steam' ? (
        <div className="card stack">
          <p className="sub">
            Ключ Web API: steamcommunity.com/dev/apikey. Steam ID — 17 цифр из ссылки на профиль. Cookie
            steamLoginSecure необязательна и нужна для загрузки ожидающих заявок.
          </p>
          <div className="fields">
            {secret('steam.api_key', 'Steam Web API key', draft.steam.api_key)}
            <Field label="Ваш Steam ID (64)">
              <input value={draft.steam.steam_id} onChange={(e) => set('steam', { steam_id: e.target.value.trim() })} />
            </Field>
            {secret('steam.login_secure', 'Cookie steamLoginSecure', draft.steam.login_secure)}
          </div>
          {saveButton('steam')}
        </div>
      ) : null}

      {tab === 'Друзья' ? (
        <div className="card stack">
          <div className="fields">
            <Field label="Обновлять друзей из Steam, часов" hint="0 — только вручную">
              <input type="number" min={0} value={draft.friends.refresh_hours} onChange={(e) => set('friends', { refresh_hours: Number(e.target.value) })} />
            </Field>
          </div>
          <h3>Закреплённые друзья</h3>
          <ProtectedList
            items={draft.friends.protected}
            onChange={(protectedList) => set('friends', { protected: protectedList })}
          />
          {saveButton('friends')}
        </div>
      ) : null}

      {tab === 'Пользователи' ? <UsersCard /> : null}

      {tab === 'Данные' ? (
        <div className="card stack">
          <h2>Выгрузка базы</h2>
          <p className="sub">
            ZIP с коллекциями MongoDB в JSONL: заказы, друзья Steam и логи. Пароли и
            ключи в архив не попадают.
          </p>
          <div className="row">
            <Action className="primary" onRun={() => api.download('/data/export', 'funpay-db.zip')}>
              Скачать базу (ZIP)
            </Action>
            <Action onRun={() => api.download('/logs/export', 'logs.jsonl')}>Скачать логи</Action>
          </div>
        </div>
      ) : null}
    </>
  )
}

function SecretField(props: {
  label: string
  current: Secret
  value: string | null | undefined
  hint?: ReactNode
  onChange: (v: string | null) => void
}) {
  const cleared = props.value === null
  return (
    <Field
      label={props.label}
      hint={
        cleared
          ? 'будет удалён при сохранении'
          : props.current.is_set
            ? `задан (${props.current.hint || 'скрыт'}); оставьте пустым, чтобы не менять`
            : 'не задан'
      }
    >
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <input
          type="password"
          autoComplete="off"
          value={props.value ?? ''}
          placeholder={props.current.is_set ? '••••••••' : ''}
          onChange={(e) => props.onChange(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
        {props.current.is_set ? (
          <button type="button" className="danger" onClick={() => props.onChange(null)} title="Удалить ключ">
            ✕
          </button>
        ) : null}
      </div>
    </Field>
  )
}

function ProtectedList(props: {
  items: { steam_id: string; note: string }[]
  onChange: (items: { steam_id: string; note: string }[]) => void
}) {
  const [id, setId] = useState('')
  const [note, setNote] = useState('')
  return (
    <div className="stack">
      {props.items.map((p) => (
        <div key={p.steam_id} className="row">
          <code>{p.steam_id}</code>
          <span className="sub">{p.note}</span>
          <button className="danger" onClick={() => props.onChange(props.items.filter((x) => x.steam_id !== p.steam_id))}>
            Убрать
          </button>
        </div>
      ))}
      <div className="row">
        <input placeholder="Steam ID (17 цифр)" value={id} onChange={(e) => setId(e.target.value.trim())} aria-label="Steam ID" />
        <input placeholder="Кто это" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Заметка" />
        <button
          disabled={!/^\d{17}$/.test(id)}
          onClick={() => {
            props.onChange([...props.items.filter((x) => x.steam_id !== id), { steam_id: id, note }])
            setId('')
            setNote('')
          }}
        >
          Добавить
        </button>
      </div>
    </div>
  )
}

function UsersCard() {
  const users = useLoad(() => api.get<User[]>('/users'))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [own, setOwn] = useState('')
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')
  return (
    <div className="grid2">
      <div className="card stack">
        <h2>Пользователи</h2>
        <Alert kind="bad">{error || users.error}</Alert>
        <table>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.username}>
                <td>{u.username}</td>
                <td className="sub">{fmtDate(u.created_at)}</td>
                <td>
                  <Action
                    className="danger"
                    confirm={`Удалить пользователя ${u.username}?`}
                    onError={setError}
                    onRun={async () => {
                      await api.del(`/users/${encodeURIComponent(u.username)}`)
                      await users.reload()
                    }}
                  >
                    Удалить
                  </Action>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          <input placeholder="логин" value={username} onChange={(e) => setUsername(e.target.value)} aria-label="Логин" />
          <input type="password" placeholder="пароль (от 8 символов)" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Пароль" autoComplete="new-password" />
          <Action
            onError={setError}
            onRun={async () => {
              await api.post('/users', { username, password })
              setUsername('')
              setPassword('')
              setError('')
              await users.reload()
            }}
          >
            Добавить
          </Action>
        </div>
      </div>
      <div className="card stack">
        <h2>Мой пароль</h2>
        <Alert kind="good">{ok}</Alert>
        <input type="password" placeholder="новый пароль" value={own} onChange={(e) => setOwn(e.target.value)} aria-label="Новый пароль" autoComplete="new-password" />
        <Action
          onError={setError}
          onRun={async () => {
            await api.post('/auth/password', { password: own })
            setOwn('')
            setOk('Пароль изменён')
          }}
        >
          Сменить пароль
        </Action>
      </div>
    </div>
  )
}

function RaiseStatusBlock() {
  const status = useLoad(() => api.get<RaiseStatus>('/funpay/raise'))
  const [error, setError] = useState('')
  return (
    <div className="stack">
      <Alert kind="bad">{error || status.error}</Alert>
      {status.data && status.data.categories.length ? (
        <table>
          <thead>
            <tr>
              <th>Категория</th>
              <th>Последнее поднятие</th>
              <th>Результат</th>
              <th>Следующее</th>
            </tr>
          </thead>
          <tbody>
            {status.data.categories.map((c) => (
              <tr key={c.category_id}>
                <td>{c.category_id}</td>
                <td>{fmtDate(c.last_at)}</td>
                <td>
                  {c.ok === null ? (
                    '—'
                  ) : (
                    <span className={`badge ${c.ok ? 'good' : 'warn'}`}>{c.message || (c.ok ? 'ок' : 'ошибка')}</span>
                  )}
                </td>
                <td>{fmtDate(c.next_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="sub">Категорий пока нет: синхронизируйте продажи или укажите ID игр.</div>
      )}
      <div className="row">
        <Action
          onError={setError}
          onRun={async () => {
            setError('')
            status.setData(await api.post<RaiseStatus>('/funpay/raise'))
          }}
        >
          Поднять сейчас
        </Action>
      </div>
    </div>
  )
}
