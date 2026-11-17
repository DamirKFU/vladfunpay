import { useState } from 'react'

import { api } from '../api'
import { PromptInfo, ProductKind, ProductType, Settings } from '../types'
import { Action, Field } from './ui'

type SetFn = <S extends keyof Settings>(section: S, patch: Partial<Settings[S]>) => void
type Props = { draft: Settings; set: SetFn; save: () => Promise<void> }

const lines = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean)
const words = (text: string) => text.split(',').map((s) => s.trim()).filter(Boolean)

function SaveRow({ save, children }: { save: () => Promise<void>; children?: React.ReactNode }) {
  return (
    <div className="row">
      {children}
      <Action className="primary" onRun={save}>
        Сохранить
      </Action>
    </div>
  )
}

export function BotParamsCard({ draft, set, save }: Props) {
  const b = draft.bot
  const num = (key: keyof typeof b, label: string, hint?: string) => (
    <Field label={label} hint={hint}>
      <input
        type="number"
        min={0}
        value={b[key] as number}
        onChange={(e) => set('bot', { [key]: Number(e.target.value) } as Partial<Settings['bot']>)}
      />
    </Field>
  )
  return (
    <div className="card stack">
      <label className="check">
        <input type="checkbox" checked={b.enabled} onChange={(e) => set('bot', { enabled: e.target.checked })} />
        Бот отвечает на FunPay
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={b.only_with_open_orders}
          onChange={(e) => set('bot', { only_with_open_orders: e.target.checked })}
        />
        ИИ только в чатах с открытым заказом (экономит токены и защищает от спама)
      </label>
      <div className="fields">
        {num('reply_delay_sec', 'Задержка перед ответом, с', 'ждём паузу, чтобы склеить сообщения подряд')}
        {num('max_wait_sec', 'Потолок ожидания, с', 'ответим, даже если покупатель пишет без пауз')}
        {num('poll_interval_sec', 'Опрос FunPay, с')}
        {num('max_tokens', 'max_tokens ответа')}
        {num('daily_token_limit', 'Лимит токенов в сутки')}
        {num('chat_daily_replies', 'Ответов в одном чате в сутки')}
        {num('max_input_chars', 'Обрезать сообщение покупателя до, символов')}
        {num('history_messages', 'Сообщений истории в запросе')}
      </div>
      <SaveRow save={save} />
    </div>
  )
}

export function PromptCard({ draft, set, save }: Props) {
  const b = draft.bot
  const [info, setInfo] = useState<PromptInfo | null>(null)
  const loadInfo = async () => setInfo(await api.get<PromptInfo>('/bot/prompt'))
  return (
    <div className="card stack">
      <p className="sub">
        Здесь — как бот общается: тон, правила, примеры. Правила работы с инструментами (заказы, ассортимент, сроки
        выдачи, ссылки Steam) зашиты в код и не редактируются, чтобы бот не начал выдумывать факты. Писать можно по-русски
        или по-английски; отвечать покупателю бот всё равно будет по-русски.
      </p>
      <Field label="Правила общения" hint="Пусто — стандартный текст. Сохраните, чтобы применить.">
        <textarea
          rows={8}
          value={b.style_prompt}
          placeholder={info?.default_style ?? 'Стандартные правила: коротко, вежливо, без markdown…'}
          onChange={(e) => set('bot', { style_prompt: e.target.value })}
        />
      </Field>
      <div className="row">
        <button
          onClick={async () => {
            const data = info ?? (await api.get<PromptInfo>('/bot/prompt'))
            setInfo(data)
            set('bot', { style_prompt: data.default_style })
          }}
        >
          Вставить стандартный текст
        </button>
        <button onClick={() => set('bot', { style_prompt: '' })}>Сбросить к стандартному</button>
      </div>
      <Field label="Ответ, когда чат уходит вам" hint="например, при проблеме со входом в купленный аккаунт">
        <input value={b.handoff_reply} onChange={(e) => set('bot', { handoff_reply: e.target.value })} />
      </Field>
      <Field label="Заметки продавца" hint="Факты о магазине: гарантия, часы работы, что делать при задержках.">
        <textarea rows={4} value={b.seller_notes} onChange={(e) => set('bot', { seller_notes: e.target.value })} />
      </Field>
      <h3>Примеры ответов</h3>
      <p className="sub">Как отвечать на типичные сообщения. ИИ подстраивает тон и содержание под них, но факты берёт из инструментов.</p>
      {b.examples.map((ex, i) => (
        <div key={i} className="grid2" style={{ gap: 8 }}>
          <textarea
            rows={2}
            placeholder="Покупатель пишет…"
            value={ex.buyer}
            aria-label="Сообщение покупателя"
            onChange={(e) => {
              const examples = [...b.examples]
              examples[i] = { ...ex, buyer: e.target.value }
              set('bot', { examples })
            }}
          />
          <div className="row" style={{ alignItems: 'stretch', flexWrap: 'nowrap' }}>
            <textarea
              rows={2}
              placeholder="Бот отвечает…"
              value={ex.reply}
              aria-label="Ответ бота"
              style={{ flex: 1 }}
              onChange={(e) => {
                const examples = [...b.examples]
                examples[i] = { ...ex, reply: e.target.value }
                set('bot', { examples })
              }}
            />
            <button className="danger" onClick={() => set('bot', { examples: b.examples.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        </div>
      ))}
      <SaveRow save={save}>
        <button onClick={() => set('bot', { examples: [...b.examples, { buyer: '', reply: '' }] })}>Добавить пример</button>
      </SaveRow>
      <details
        onToggle={(e) => {
          if ((e.target as HTMLDetailsElement).open) void loadInfo()
        }}
      >
        <summary>Итоговый промпт (как его видит ИИ, после сохранения)</summary>
        <pre className="code">{info?.composed ?? 'Загрузка…'}</pre>
      </details>
    </div>
  )
}

export function TemplatesCard({ draft, set, save }: Props) {
  const b = draft.bot
  const update = (i: number, patch: Partial<(typeof b.templates)[number]>) => {
    const templates = [...b.templates]
    templates[i] = { ...templates[i], ...patch }
    set('bot', { templates })
  }
  return (
    <div className="card stack">
      <p className="sub">
        Готовые ответы без ИИ (бесплатно и мгновенно). Впишите несколько примеров фраз покупателя — шаблон сработает, если
        сообщение похоже на любую из них. Слова-ключи — запасной вариант: срабатывают на вхождение слова. В ответе можно
        писать {'{buyer}'} — подставится ник.
      </p>
      <Field label="Чувствительность" hint="0.6 — по умолчанию. Выше — строже (меньше ложных срабатываний).">
        <input
          type="number"
          step={0.05}
          min={0.3}
          max={1}
          value={b.template_threshold}
          onChange={(e) => set('bot', { template_threshold: Number(e.target.value) })}
          style={{ maxWidth: 120 }}
        />
      </Field>
      {b.templates.map((t, i) => (
        <div key={i} className="card stack" style={{ marginBottom: 0 }}>
          <div className="grid2" style={{ gap: 8 }}>
            <Field label="Примеры фраз покупателя" hint="по одной на строку">
              <textarea
                rows={3}
                value={t.examples.join('\n')}
                placeholder={'Когда я получу предмет?\nСколько ждать подарок?'}
                onChange={(e) => update(i, { examples: e.target.value.split('\n') })}
                onBlur={(e) => update(i, { examples: lines(e.target.value) })}
              />
            </Field>
            <Field label="Ответ">
              <textarea rows={3} value={t.reply} onChange={(e) => update(i, { reply: e.target.value })} />
            </Field>
          </div>
          <div className="row">
            <input
              placeholder="слова-ключи через запятую (необязательно)"
              value={t.keywords.join(', ')}
              onChange={(e) => update(i, { keywords: words(e.target.value) })}
              aria-label="Слова-ключи"
              style={{ flex: 1, minWidth: 200 }}
            />
            <button className="danger" onClick={() => set('bot', { templates: b.templates.filter((_, j) => j !== i) })}>
              Удалить шаблон
            </button>
          </div>
        </div>
      ))}
      <SaveRow save={save}>
        <button onClick={() => set('bot', { templates: [...b.templates, { examples: [], keywords: [], reply: '' }] })}>
          Добавить шаблон
        </button>
      </SaveRow>
    </div>
  )
}

const KINDS: [ProductKind, string][] = [
  ['gift', 'Подарок Steam (дружба N дней, лимит в день)'],
  ['trade', 'Обмен по трейд-ссылке'],
  ['account', 'Аккаунт (автовыдача FunPay)'],
  ['manual', 'Другое (выдаёт продавец)'],
]

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '') || `type_${Date.now() % 100000}`

export function CatalogCard({ draft, set, save }: Props) {
  const c = draft.catalog
  const [presets, setPresets] = useState<ProductType[] | null>(null)
  const update = (i: number, patch: Partial<ProductType>) => {
    const types = [...c.types]
    types[i] = { ...types[i], ...patch }
    set('catalog', { types })
  }
  const missing = (presets ?? []).filter((p) => !c.types.some((t) => t.id === p.id))
  return (
    <div className="card stack">
      <p className="sub">
        Тип товара говорит боту, как выдаётся лот и как с покупателем о нём говорить. Тип лота определяется так: ваш
        ручной выбор на странице «Лоты» → слова-ключи → ИИ читает описание карточки и сравнивает с описаниями типов →
        тип по умолчанию.
      </p>
      <div className="fields">
        <Field label="Тип по умолчанию">
          <select value={c.default_type} onChange={(e) => set('catalog', { default_type: e.target.value })}>
            {c.types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <label className="check">
        <input type="checkbox" checked={c.classify_with_ai} onChange={(e) => set('catalog', { classify_with_ai: e.target.checked })} />
        Определять тип лота ИИ по описанию карточки (когда не сработали слова-ключи)
      </label>
      {c.types.map((t, i) => (
        <div key={i} className="card stack" style={{ marginBottom: 0 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <b>{t.name || 'Новый тип'}</b>
            <span className="sub">id: {t.id}</span>
          </div>
          <div className="fields">
            <Field label="Название">
              <input value={t.name} onChange={(e) => update(i, { name: e.target.value })} />
            </Field>
            <Field label="Способ выдачи">
              <select value={t.kind} onChange={(e) => update(i, { kind: e.target.value as ProductKind })}>
                {KINDS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
            {t.kind === 'gift' ? (
              <>
                <Field label="Дней дружбы до подарка" hint="Steam требует 30 для Dota 2">
                  <input type="number" min={0} value={t.friend_days} onChange={(e) => update(i, { friend_days: Number(e.target.value) })} />
                </Field>
                <Field label="Подарков в день" hint="очередь сдвигается, когда лимит дня занят">
                  <input type="number" min={1} value={t.per_day} onChange={(e) => update(i, { per_day: Number(e.target.value) })} />
                </Field>
              </>
            ) : null}
            {t.kind === 'trade' || t.kind === 'manual' ? (
              <Field label="Срок выдачи, часов после оплаты">
                <input type="number" min={0} value={t.send_hours} onChange={(e) => update(i, { send_hours: Number(e.target.value) })} />
              </Field>
            ) : null}
          </div>
          <Field label="Описание для ИИ: какие лоты относятся к типу" hint="ИИ сравнивает с ним описание карточки лота">
            <textarea rows={2} value={t.description} onChange={(e) => update(i, { description: e.target.value })} />
          </Field>
          <Field label="Инструкция для ИИ: как работать с покупателем" hint="добавляется в промпт, когда у покупателя есть заказ этого типа">
            <textarea rows={4} value={t.instructions} onChange={(e) => update(i, { instructions: e.target.value })} />
          </Field>
          <div className="grid2" style={{ gap: 8 }}>
            <Field label="Слова-ключи (без ИИ)" hint="в названии или описании лота, через запятую">
              <input value={t.keywords.join(', ')} onChange={(e) => update(i, { keywords: words(e.target.value) })} />
            </Field>
            <Field label="Слова «сразу владельцу»" hint="если покупатель с таким заказом пишет их — чат уходит вам без ИИ">
              <input value={t.handoff_keywords.join(', ')} onChange={(e) => update(i, { handoff_keywords: words(e.target.value) })} />
            </Field>
          </div>
          <div className="row">
            <button
              className="danger"
              disabled={c.types.length <= 1}
              onClick={() => set('catalog', { types: c.types.filter((_, j) => j !== i) })}
            >
              Удалить тип
            </button>
          </div>
        </div>
      ))}
      <SaveRow save={save}>
        <button
          onClick={() => {
            const name = window.prompt('Название нового типа') ?? ''
            if (!name.trim()) return
            set('catalog', {
              types: [
                ...c.types,
                {
                  id: slug(name),
                  name,
                  kind: 'manual',
                  description: '',
                  instructions: '',
                  keywords: [],
                  handoff_keywords: [],
                  friend_days: 30,
                  per_day: 8,
                  send_hours: 24,
                },
              ],
            })
          }}
        >
          Добавить тип
        </button>
        <button onClick={async () => setPresets(await api.get<ProductType[]>('/catalog/presets'))}>
          Показать готовые типы
        </button>
      </SaveRow>
      {presets ? (
        missing.length ? (
          <div className="row">
            {missing.map((p) => (
              <button key={p.id} onClick={() => set('catalog', { types: [...c.types, p] })}>
                + {p.name}
              </button>
            ))}
          </div>
        ) : (
          <div className="sub">Все готовые типы уже добавлены.</div>
        )
      ) : null}
    </div>
  )
}
