const TOKEN_KEY = 'fp-token'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* приватный режим: токен живёт до перезагрузки */
  }
}

let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const resp = await fetch(`/api${path}`, { ...init, headers })
  if (resp.status === 401 && token) {
    setToken(null)
    onUnauthorized()
  }
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`
    try {
      const data = await resp.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) {
        message = data.detail.map((d: { msg: string }) => d.msg).join('; ')
      }
    } catch {
      /* не JSON */
    }
    if (resp.status >= 500) reportClientError(`API ${path}: ${message}`)
    throw new ApiError(resp.status, message)
  }
  return resp
}

export const api = {
  get: async <T>(path: string): Promise<T> => (await request(path)).json(),
  text: async (path: string): Promise<string> => (await request(path)).text(),
  post: async <T>(path: string, body?: unknown): Promise<T> =>
    (await request(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    })).json(),
  put: async <T>(path: string, body: unknown): Promise<T> =>
    (await request(path, { method: 'PUT', body: JSON.stringify(body) })).json(),
  patch: async <T>(path: string, body: unknown): Promise<T> =>
    (await request(path, { method: 'PATCH', body: JSON.stringify(body) })).json(),
  del: async <T>(path: string): Promise<T> =>
    (await request(path, { method: 'DELETE' })).json(),
  download: async (path: string, fallbackName: string): Promise<void> => {
    const resp = await request(path)
    const disposition = resp.headers.get('Content-Disposition') ?? ''
    const match = /filename="([^"]+)"/.exec(disposition)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = match?.[1] ?? fallbackName
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

let lastReport = 0
/** Ошибки браузера — в общий лог на сервере (не чаще раза в 2 секунды). */
export function reportClientError(message: string, stack?: string): void {
  const now = Date.now()
  if (!getToken() || now - lastReport < 2000) return
  lastReport = now
  void fetch('/api/logs/client', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
    body: JSON.stringify({
      message: String(message).slice(0, 2000),
      url: location.pathname,
      stack: (stack ?? '').slice(0, 4000),
    }),
  }).catch(() => {})
}
