import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { errorText } from '../api'

export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const loadRef = useRef(load)
  loadRef.current = load

  const reload = useCallback(async () => {
    try {
      setData(await loadRef.current())
      setError('')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, setData, error, loading, reload }
}

export function usePolling(fn: () => void, ms: number, enabled = true) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (!enabled) return
    const id = setInterval(() => ref.current(), ms)
    return () => clearInterval(id)
  }, [ms, enabled])
}

/** Кнопка, которая сама показывает «…» и ошибку действия. */
export function Action(props: {
  onRun: () => Promise<unknown>
  children: ReactNode
  className?: string
  disabled?: boolean
  confirm?: string
  onError?: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)
  return (
    <button
      className={props.className}
      disabled={busy || props.disabled}
      onClick={async () => {
        if (props.confirm && !window.confirm(props.confirm)) return
        setBusy(true)
        try {
          await props.onRun()
        } catch (e) {
          if (props.onError) props.onError(errorText(e))
          else window.alert(errorText(e))
        } finally {
          setBusy(false)
        }
      }}
    >
      {busy ? '…' : props.children}
    </button>
  )
}

export function Alert({ kind, children }: { kind: 'bad' | 'good' | 'warn'; children: ReactNode }) {
  if (!children) return null
  return <div className={`alert ${kind}`} role={kind === 'bad' ? 'alert' : 'status'}>{children}</div>
}

export function Field(props: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
      {props.hint ? <small>{props.hint}</small> : null}
    </label>
  )
}

export function Tile(props: { k: string; v: ReactNode; d?: ReactNode }) {
  return (
    <div className="tile">
      <div className="k">{props.k}</div>
      <div className="v">{props.v}</div>
      {props.d ? <div className="d">{props.d}</div> : null}
    </div>
  )
}

const dtf = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Europe/Moscow',
})

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : dtf.format(d)
}

export const nf = new Intl.NumberFormat('ru-RU')
export const rub = (v: number) => `${nf.format(Math.round(v))} ₽`
