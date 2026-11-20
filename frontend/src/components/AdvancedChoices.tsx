import type { Schemas } from '../api/client'

type Lookups = Schemas['LookupsOut']
type Ids = Schemas['Defaults']

function Choice({ label, options, value, fallback, onChange }: {
  label: string
  options: Schemas['Named'][]
  value: number | null
  fallback: number | null
  onChange: (id: number) => void
}) {
  return (
    <label className="field">
      {label}
      <select value={value ?? fallback ?? ''} onChange={(e) => onChange(Number(e.target.value))}>
        {fallback === null && <option value="">Choose…</option>}
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.name}{o.id === fallback ? ' (default)' : ''}</option>
        ))}
      </select>
    </label>
  )
}

const NONE: Ids = { domain_id: null, group_id: null, source_id: null }

/** Domain / group / source, defaulting to the .env values the backend resolved. */
export default function AdvancedChoices({ lookups, overrides, onChange }: {
  lookups: Lookups | null
  overrides: Ids
  onChange: (overrides: Ids) => void
}) {
  const defaults = lookups?.defaults ?? NONE
  const set = (key: keyof Ids) => (id: number) => onChange({ ...overrides, [key]: id })
  return (
    <>
      {lookups?.problems.map((p) => <p key={p} className="warn-text">{p}</p>)}
      <details>
        <summary>Advanced · domain, group, source</summary>
        <div className="advanced">
          <Choice label="Domain" options={lookups?.domains ?? []} value={overrides.domain_id}
            fallback={defaults.domain_id} onChange={set('domain_id')} />
          <Choice label="Group" options={lookups?.groups ?? []} value={overrides.group_id}
            fallback={defaults.group_id} onChange={set('group_id')} />
          <Choice label="Traffic source" options={lookups?.sources ?? []} value={overrides.source_id}
            fallback={defaults.source_id} onChange={set('source_id')} />
        </div>
      </details>
    </>
  )
}
