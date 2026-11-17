import { FormEvent, useEffect, useState } from 'react'

import { api, errorText } from '../api'
import { Alert, Field } from '../components/ui'

export default function LoginPage(props: { onLogin: (token: string, username: string) => void }) {
  const [setup, setSetup] = useState<boolean | null>(null)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<{ needs_setup: boolean }>('/auth/state')
      .then((s) => setSetup(s.needs_setup))
      .catch((e) => setError(errorText(e)))
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api.post<{ token: string; username: string }>(
        setup ? '/auth/setup' : '/auth/login',
        { username, password },
      )
      props.onLogin(res.token, res.username)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="card stack" onSubmit={submit}>
        <h1>{setup ? 'Первый запуск' : 'Вход'}</h1>
        {setup ? (
          <p className="sub">Создайте администратора. Пароль — не короче 8 символов.</p>
        ) : null}
        <Alert kind="bad">{error}</Alert>
        <Field label="Логин">
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </Field>
        <Field label="Пароль">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={setup ? 'new-password' : 'current-password'}
            required
          />
        </Field>
        <button className="primary" disabled={busy || setup === null}>
          {setup ? 'Создать и войти' : 'Войти'}
        </button>
      </form>
    </div>
  )
}
