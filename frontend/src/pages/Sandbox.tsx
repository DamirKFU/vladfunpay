import { FormEvent, useState } from 'react'

import { api } from '../api'
import { Messages, Traces } from '../components/ChatPanel'
import { Action, Alert, Field, rub, useLoad, usePolling } from '../components/ui'
import { BotStatus, ChatView, Conversation, Offer, OpenOrder, SandboxFriendship } from '../types'

const EMPTY_OFFER: Offer = {
  offer_id: '',
  title: '',
  price: 0,
  amount: 1,
  category: '',
  auto_delivery: false,
  description: '',
}

export default function SandboxPage() {
  const convs = useLoad(() => api.get<Conversation[]>('/bot/sandbox/conversations'))
  const offers = useLoad(() => api.get<Offer[]>('/sandbox/offers'))
  const status = useLoad(() => api.get<BotStatus>('/bot/status'))
  const [selected, setSelected] = useState<string | null>(null)
  const chat = useLoad(
    () => (selected ? api.get<ChatView>(`/bot/sandbox/conversations/${selected}`) : Promise.resolve(null)),
    [selected],
  )
  const orders = useLoad(
    () => (selected ? api.get<OpenOrder[]>(`/sandbox/orders?chat_id=${selected}`) : Promise.resolve([])),
    [selected],
  )
  const [text, setText] = useState('')
  const [buyer, setBuyer] = useState('test_buyer')
  const [error, setError] = useState('')

  usePolling(() => {
    if (selected) void chat.reload()
    void status.reload()
  }, 1500)

  async function send(e: FormEvent) {
    e.preventDefault()
    if (!selected || !text.trim()) return
    try {
      await api.post(`/sandbox/chats/${selected}/messages`, { text })
      setText('')
      await chat.reload()
    } catch (err) {
      setError(String(err))
    }
  }

  const waiting = selected && status.data?.sandbox.pending_chats.includes(selected)

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Песочница</h1>
          <div className="sub">
            Пишите боту как покупатель и делайте тестовые заказы. Бот отвечает тем же конвейером, что и на FunPay:
            та же склейка сообщений, лимиты, инструменты и ИИ. FunPay не затрагивается.
          </div>
        </div>
      </div>
      <Alert kind="bad">{error}</Alert>
      {status.data && !status.data.llm_configured ? (
        <Alert kind="warn">ИИ не настроен — ответят только шаблоны. Ключ Яндекса задаётся в «Настройках».</Alert>
      ) : null}
      <div className="grid2 grid-side">
        <div className="card stack">
          <h2>Покупатели</h2>
          <div className="row">
            <input value={buyer} onChange={(e) => setBuyer(e.target.value)} aria-label="Ник покупателя" style={{ flex: 1, minWidth: 0 }} />
            <Action
              onError={setError}
              onRun={async () => {
                const conv = await api.post<Conversation>('/sandbox/chats', { buyer_name: buyer })
                await convs.reload()
                setSelected(conv.chat_id)
              }}
            >
              Добавить
            </Action>
          </div>
          <div className="list">
            {(convs.data ?? []).map((c) => (
              <button key={c.chat_id} className={c.chat_id === selected ? 'on' : ''} onClick={() => setSelected(c.chat_id)}>
                <b>{c.buyer_name}</b>
                <span className="sub">{c.chat_id}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="card stack">
          {selected && chat.data ? (
            <>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <h2>Чат с {chat.data.conversation.buyer_name}</h2>
                <div className="row">
                  {chat.data.conversation.needs_human ? (
                    <Action
                      onRun={async () => {
                        await api.post(`/bot/sandbox/conversations/${selected}/resume`)
                        await chat.reload()
                      }}
                    >
                      Вернуть боту
                    </Action>
                  ) : null}
                  <Action
                    confirm="Очистить переписку этого покупателя?"
                    onRun={async () => {
                      await api.post(`/sandbox/chats/${selected}/reset`)
                      await chat.reload()
                    }}
                  >
                    Очистить чат
                  </Action>
                </div>
              </div>
              {chat.data.conversation.needs_human ? (
                <Alert kind="warn">Бот передал чат продавцу: {chat.data.conversation.human_reason}</Alert>
              ) : null}
              <FriendshipControl chatId={selected} />
              <Messages messages={chat.data.messages} />
              {waiting ? <div className="sub">Бот ждёт паузу в сообщениях, затем ответит…</div> : null}
              <form className="row" onSubmit={send}>
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Сообщение от покупателя"
                  aria-label="Сообщение от покупателя"
                  style={{ flex: 1, minWidth: 0 }}
                />
                <button className="primary" disabled={!text.trim()}>
                  Отправить
                </button>
              </form>
            </>
          ) : (
            <div className="sub">Добавьте покупателя или выберите его слева.</div>
          )}
        </div>
      </div>
      {selected ? (
        <div className="grid2" style={{ marginTop: 16 }}>
          <OrdersCard chatId={selected} orders={orders.data ?? []} offers={offers.data ?? []} reload={async () => {
            await orders.reload()
            await offers.reload()
          }} />
          <div className="card">
            <h2>Как бот решал</h2>
            <Traces traces={chat.data?.traces ?? []} />
          </div>
        </div>
      ) : null}
      <OffersCard offers={offers.data ?? []} reload={offers.reload} />
    </>
  )
}

function OrdersCard(props: { chatId: string; orders: OpenOrder[]; offers: Offer[]; reload: () => Promise<void> }) {
  const [offerId, setOfferId] = useState('')
  const [title, setTitle] = useState('')
  const [price, setPrice] = useState(100)
  return (
    <div className="card stack">
      <h2>Заказы покупателя</h2>
      <div className="row">
        <select value={offerId} onChange={(e) => setOfferId(e.target.value)} aria-label="Лот">
          <option value="">Свой товар…</option>
          {props.offers.map((o) => (
            <option key={o.offer_id} value={o.offer_id}>
              {o.title} — {rub(o.price)}
            </option>
          ))}
        </select>
        {!offerId ? (
          <>
            <input placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Название" />
            <input type="number" min={0} value={price} onChange={(e) => setPrice(Number(e.target.value))} aria-label="Цена" style={{ width: 100 }} />
          </>
        ) : null}
        <Action
          className="primary"
          onRun={async () => {
            await api.post('/sandbox/orders', {
              chat_id: props.chatId,
              offer_id: offerId || null,
              title,
              price,
            })
            await props.reload()
          }}
        >
          Оплатить заказ
        </Action>
      </div>
      {props.orders.length ? (
        <table>
          <thead>
            <tr>
              <th>Заказ</th>
              <th>Товар</th>
              <th className="num">Цена</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {props.orders.map((o) => (
              <tr key={o.order_id}>
                <td>#{o.order_id}</td>
                <td>{o.title}</td>
                <td className="num">{rub(o.price)}</td>
                <td>
                  <select
                    value={o.status}
                    aria-label={`Статус заказа ${o.order_id}`}
                    onChange={async (e) => {
                      await api.patch(`/sandbox/orders/${o.order_id}`, { status: e.target.value })
                      await props.reload()
                    }}
                  >
                    <option value="paid">Оплачен</option>
                    <option value="closed">Закрыт</option>
                    <option value="refunded">Возврат</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="sub">Заказов нет. Без открытого заказа бот по умолчанию не отвечает (см. настройки бота).</div>
      )}
    </div>
  )
}

function OffersCard(props: { offers: Offer[]; reload: () => Promise<void> }) {
  const [draft, setDraft] = useState<Offer>(EMPTY_OFFER)
  return (
    <div className="card stack">
      <h2>Тестовые лоты (тип каждого лота — на странице «Лоты», вкладка «Песочница»)</h2>
      <div className="row">
        <input placeholder="Название лота" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} aria-label="Название лота" />
        <input type="number" min={0} value={draft.price} onChange={(e) => setDraft({ ...draft, price: Number(e.target.value) })} aria-label="Цена лота" style={{ width: 100 }} />
        <input type="number" min={0} value={draft.amount ?? 0} onChange={(e) => setDraft({ ...draft, amount: Number(e.target.value) })} aria-label="Количество" style={{ width: 90 }} />
        <label className="check">
          <input type="checkbox" checked={draft.auto_delivery} onChange={(e) => setDraft({ ...draft, auto_delivery: e.target.checked })} />
          автовыдача
        </label>
        <textarea
          rows={2}
          placeholder="Описание карточки (по нему ИИ поймёт тип: подарок, обмен, аккаунт)"
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
          aria-label="Описание лота"
          style={{ flex: '1 1 100%' }}
        />
        <Action
          disabled={!draft.title.trim()}
          onRun={async () => {
            await api.put('/sandbox/offers', draft)
            setDraft(EMPTY_OFFER)
            await props.reload()
          }}
        >
          {draft.offer_id ? 'Сохранить' : 'Добавить лот'}
        </Action>
      </div>
      {props.offers.length ? (
        <table>
          <thead>
            <tr>
              <th>Лот</th>
              <th className="num">Цена</th>
              <th className="num">В наличии</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {props.offers.map((o) => (
              <tr key={o.offer_id}>
                <td>{o.title}</td>
                <td className="num">{rub(o.price)}</td>
                <td className="num">{o.amount ?? '—'}</td>
                <td className="row">
                  <button onClick={() => setDraft(o)}>Изменить</button>
                  <Action
                    className="danger"
                    onRun={async () => {
                      await api.del(`/sandbox/offers/${o.offer_id}`)
                      await props.reload()
                    }}
                  >
                    Удалить
                  </Action>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Field label="" hint="Добавьте пару лотов, чтобы проверить ответы про цены и наличие.">
          <span />
        </Field>
      )}
    </div>
  )
}

const DAY_MS = 86_400_000

function FriendshipControl({ chatId }: { chatId: string }) {
  const state = useLoad(() => api.get<SandboxFriendship>(`/sandbox/chats/${chatId}/friendship`), [chatId])
  const [days, setDays] = useState(10)
  const rel = state.data?.relationship ?? ''
  const since = state.data?.since ? new Date(state.data.since) : null
  const currentDays = since ? Math.floor((Date.now() - since.getTime()) / DAY_MS) : null

  async function apply(relationship: string, daysAgo: number) {
    const body =
      relationship === 'friend'
        ? { relationship, since: new Date(Date.now() - daysAgo * DAY_MS).toISOString() }
        : { relationship: relationship || null }
    state.setData(await api.put<SandboxFriendship>(`/sandbox/chats/${chatId}/friendship`, body))
  }

  return (
    <div className="row sub" style={{ background: 'var(--surface-2)', padding: '6px 10px', borderRadius: 8 }}>
      <span>Steam (симуляция для сроков подарка):</span>
      <select value={rel} onChange={(e) => void apply(e.target.value, days)} aria-label="Дружба в Steam">
        <option value="">не в друзьях</option>
        <option value="friend">в друзьях</option>
        <option value="invite_sent">мы отправили заявку</option>
        <option value="invite_received">покупатель отправил заявку</option>
      </select>
      {rel === 'friend' ? (
        <>
          <span>уже</span>
          <input
            type="number"
            min={0}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            onBlur={() => void apply('friend', days)}
            aria-label="Дней в друзьях"
            style={{ width: 70 }}
          />
          <span>дн.{currentDays !== null && currentDays !== days ? ` (сейчас ${currentDays})` : ''}</span>
        </>
      ) : null}
    </div>
  )
}
