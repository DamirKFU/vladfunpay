import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { api, getToken, setToken, setUnauthorizedHandler } from './api'
import JournalPage from './pages/Journal'
import Dashboard from './pages/Dashboard'
import LoginPage from './pages/Login'
import LogsPage from './pages/Logs'
import SettingsPage from './pages/Settings'
import SteamPage from './pages/Steam'

const NAV = [
  ['/', 'Продажи'],
  ['/journal', 'Заказы'],
  ['/steam', 'Друзья Steam'],
  ['/logs', 'Логи'],
  ['/settings', 'Настройки'],
] as const

export default function App() {
  const [user, setUser] = useState<string | null>(null)
  const [checked, setChecked] = useState(false)
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    if (!getToken()) {
      setChecked(true)
      return
    }
    api
      .get<{ username: string }>('/auth/me')
      .then((me) => setUser(me.username))
      .catch(() => setToken(null))
      .finally(() => setChecked(true))
  }, [])

  if (!checked) return null
  if (!user) {
    return (
      <LoginPage
        onLogin={(token, username) => {
          setToken(token)
          setUser(username)
        }}
      />
    )
  }

  return (
    <div className="shell">
      <nav className="nav" aria-label="Разделы">
        <div className="brand">FunPay Seller</div>
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/'}>
            {label}
          </NavLink>
        ))}
        <div className="spacer" />
        <div className="who">Вы вошли как {user}</div>
        <button
          onClick={() => {
            setToken(null)
            setUser(null)
          }}
        >
          Выйти
        </button>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/steam" element={<SteamPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  )
}
