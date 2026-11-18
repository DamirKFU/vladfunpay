export type StatusDef = { value: string; label: string; kind: string }

/** Фильтр-«чипы» по статусам со счётчиками (как отборы в журнале 1С). */
export function StatusChips(props: {
  statuses: StatusDef[]
  selected: string[]
  counts: Record<string, number>
  onChange: (selected: string[]) => void
}) {
  const total = Object.values(props.counts).reduce((a, b) => a + b, 0)
  return (
    <div className="chips" role="group" aria-label="Отбор по статусу">
      <button className={props.selected.length === 0 ? 'on' : ''} aria-pressed={props.selected.length === 0} onClick={() => props.onChange([])}>
        Все<span className="n">{total}</span>
      </button>
      {props.statuses.map((s) => {
        const on = props.selected.includes(s.value)
        return (
          <button
            key={s.value}
            className={on ? 'on' : ''}
            aria-pressed={on}
            onClick={() =>
              props.onChange(on ? props.selected.filter((v) => v !== s.value) : [...props.selected, s.value])
            }
          >
            {s.label}
            <span className="n">{props.counts[s.value] ?? 0}</span>
          </button>
        )
      })}
    </div>
  )
}

export function StatusBadge({ def }: { def?: StatusDef }) {
  if (!def) return null
  return <span className={`badge ${def.kind}`}>{def.label}</span>
}
