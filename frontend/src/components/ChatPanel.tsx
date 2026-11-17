import { useEffect, useRef } from 'react'

import { BotTrace, ChatMessage } from '../types'
import { fmtDate } from './ui'

const AUTHOR = { buyer: 'Покупатель', bot: 'Бот', seller: 'Вы', system: 'FunPay' }

export function Messages({ messages }: { messages: ChatMessage[] }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages.length])
  if (!messages.length) return <div className="sub">Сообщений пока нет.</div>
  return (
    <div className="chat" aria-live="polite">
      {messages.map((m) => (
        <div key={m.message_id} className={`bubble ${m.author}`}>
          {m.text}
          <div className="meta">
            {AUTHOR[m.author]} · {fmtDate(m.created_at)}
          </div>
        </div>
      ))}
      <div ref={end} />
    </div>
  )
}

const OUTCOME: Record<BotTrace['outcome'], [string, string]> = {
  replied: ['good', 'ответ ИИ'],
  template: ['good', 'шаблон'],
  handoff: ['warn', 'передан продавцу'],
  skipped: ['warn', 'пропуск'],
  discarded: ['warn', 'пересобран'],
  error: ['bad', 'ошибка'],
}

export function Traces({ traces }: { traces: BotTrace[] }) {
  if (!traces.length) return <div className="sub">Бот ещё не отвечал в этом чате.</div>
  return (
    <div>
      {traces.map((t, i) => {
        const [kind, label] = OUTCOME[t.outcome]
        return (
          <div key={i} className="trace">
            <div className="row">
              <span className={`badge ${kind}`}>{label}</span>
              <span className="sub">{fmtDate(t.created_at)}</span>
              {t.tokens ? <span className="sub">{t.tokens} токенов</span> : null}
            </div>
            {t.detail ? <div>{t.detail}</div> : null}
            {t.tool_calls.map((c, j) => (
              <details key={j}>
                <summary>
                  Инструмент <b>{c.name}</b>
                </summary>
                <pre className="code">
                  {JSON.stringify({ arguments: c.arguments, result: c.result }, null, 2)}
                </pre>
              </details>
            ))}
          </div>
        )
      })}
    </div>
  )
}
