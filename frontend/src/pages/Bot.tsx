import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api'
import { Messages, Traces } from '../components/ChatPanel'
import { Action, Alert, Tile, fmtDate, nf, rub, useLoad, usePolling } from '../components/ui'
import { BotStatus, ChatView, Conversation, Offer } from '../types'

export default function BotPage() {
  const status = useLoad(() => api.get<BotStatus>('/bot/status'))
  const convs = useLoad(() => api.get<Conversation[]>('/bot/funpay/conversations'))
  const [selected, setSelected] = useState<string | null>(null)
  const chat = useLoad(
    () => (selected ? api.get<ChatView>(`/bot/funpay/conversations/${selected}`) : Promise.resolve(null)),
    [selected],
  )
  const [offers, setOffers] = useState<Offer[] | null>(null)
  const [error, setError] = useState('')

  usePolling(() => {
    void status.reload()
    void convs.reload()
    if (selected) void chat.reload()
  }, 5000)

  const s = status.data
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Бот FunPay</h1>
          <div className="sub">
            Отвечает покупателям в чатах FunPay. Проверить ответы без риска можно в{' '}
            <Link to="/sandbox">песочнице</Link>.
          </div>
        </div>
        {s ? (
          <Action
            className={s.enabled ? '' : 'primary'}
            onError={setError}
            onRun={async () => {
              await api.patch('/settings', { bot: { enabled: !s.enabled } })
              await status.reload()
            }}
          >
            {s.enabled ? 'Выключить бота' : 'Включить бота'}
          </Action>
        ) : null}
      </div>
      <Alert kind="bad">{error || status.error}</Alert>
      {s && !s.funpay_configured ? (
        <Alert kind="warn">Не задан golden_key FunPay — бот не может читать чаты. Откройте «Настройки».</Alert>
      ) : null}
      {s && !s.llm_configured ? (
        <Alert kind="warn">ИИ не настроен: нужны API-ключ и folder id Яндекса. Шаблоны ответов работают и без него.</Alert>
      ) : null}
      {s ? (
        <div className="tiles">
          <Tile
            k="Состояние"
            v={
              <span className={`badge ${s.enabled && s.funpay.active ? 'good' : 'warn'}`}>
                {s.enabled ? (s.funpay.active ? 'работает' : 'включён, не подключён') : 'выключен'}
              </span>
            }
            d={s.funpay.last_error || (s.funpay.last_poll_at ? `опрос ${fmtDate(s.funpay.last_poll_at)}` : '')}
          />
          <Tile
            k="Токены ИИ сегодня"
            v={nf.format(s.tokens_today)}
            d={`лимит ${nf.format(s.daily_token_limit)}`}
          />
          <Tile k="Ждут ответа" v={s.funpay.pending_chats.length} d="чаты в склейке сообщений" />
        </div>
      ) : null}
      <div className="grid2">
        <div className="card">
          <h2>Чаты</h2>
          {convs.data && convs.data.length ? (
            <div className="list">
              {convs.data.map((c) => (
                <button key={c.chat_id} className={c.chat_id === selected ? 'on' : ''} onClick={() => setSelected(c.chat_id)}>
                  <span>
                    <b>{c.buyer_name || c.chat_id}</b>{' '}
                    {c.needs_human ? <span className="badge bad">ждёт продавца</span> : null}
                  </span>
                  <span className="sub">{fmtDate(c.last_message_at)}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="sub">Пока нет переписки, которую видел бот.</div>
          )}
        </div>
        <div className="card">
          {chat.data ? (
            <div className="stack">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <h2>{chat.data.conversation.buyer_name}</h2>
                {chat.data.conversation.needs_human ? (
                  <Action
                    onRun={async () => {
                      await api.post(`/bot/funpay/conversations/${selected}/resume`)
                      await chat.reload()
                    }}
                  >
                    Вернуть боту
                  </Action>
                ) : null}
              </div>
              {chat.data.conversation.human_reason ? (
                <Alert kind="warn">Передан продавцу: {chat.data.conversation.human_reason}</Alert>
              ) : null}
              <Messages messages={chat.data.messages} />
              <h3>Как бот решал</h3>
              <Traces traces={chat.data.traces} />
            </div>
          ) : (
            <div className="sub">Выберите чат слева.</div>
          )}
        </div>
      </div>
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>Ассортимент FunPay (что видит бот)</h2>
          <Action
            onError={setError}
            onRun={async () => setOffers(await api.get<Offer[]>('/bot/funpay/assortment'))}
          >
            Загрузить лоты
          </Action>
        </div>
        {offers ? <OffersTable offers={offers} /> : <div className="sub">Нажмите «Загрузить лоты».</div>}
      </div>
    </>
  )
}

export function OffersTable({ offers }: { offers: Offer[] }) {
  if (!offers.length) return <div className="sub">Лотов нет.</div>
  return (
    <div className="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th>Лот</th>
            <th className="num">Цена</th>
            <th className="num">В наличии</th>
            <th>Автовыдача</th>
          </tr>
        </thead>
        <tbody>
          {offers.map((o) => (
            <tr key={o.offer_id}>
              <td>{o.title}</td>
              <td className="num">{rub(o.price)}</td>
              <td className="num">{o.amount ?? '—'}</td>
              <td>{o.auto_delivery ? 'да' : 'нет'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
