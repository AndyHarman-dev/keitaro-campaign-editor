import { useEffect, useState } from 'react'
import { api, call, type Schemas } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'

type Offer = Schemas['OfferOut']

interface Props {
  id: string
  label: string
  placeholder: string
  onPick: (offer: Offer) => void
  /** Called when the text is edited after a pick: the pick no longer matches the field. */
  onClear: () => void
  /** Text shown after a pick; the field clears itself when absent. */
  pickedLabel?: (offer: Offer) => string
  exclude?: number[]
}

/** Autocomplete over the offers this API key can read. */
export default function OfferPicker({ id, label, placeholder, onPick, onClear, pickedLabel, exclude = [] }: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [matches, setMatches] = useState<Offer[]>([])
  const q = useDebounced(query, 200)

  useEffect(() => {
    if (!open) return
    let current = true
    call(api.GET('/api/offers', { params: { query: { q } } })).then(
      (data) => current && setMatches(data),
      () => current && setMatches([]),
    )
    return () => {
      current = false
    }
  }, [q, open])

  function pick(offer: Offer) {
    onPick(offer)
    setQuery(pickedLabel ? pickedLabel(offer) : '')
    setOpen(false)
  }

  const shown = matches.filter((o) => !exclude.includes(o.id))
  return (
    <div className="field picker">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="text" placeholder={placeholder} value={query} autoComplete="off"
        role="combobox" aria-expanded={open && shown.length > 0} aria-controls={`${id}-list`}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); onClear() }} onFocus={() => setOpen(true)} />
      {open && shown.length > 0 && (
        <ul id={`${id}-list`} role="listbox" aria-label="Matching offers" className="options">
          {shown.slice(0, 20).map((o) => (
            <li key={o.id} role="option" aria-selected="false" tabIndex={0} className="option"
              onClick={() => pick(o)} onKeyDown={(e) => e.key === 'Enter' && pick(o)}>
              <span className="mono muted">{o.id}</span> <span>{o.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
