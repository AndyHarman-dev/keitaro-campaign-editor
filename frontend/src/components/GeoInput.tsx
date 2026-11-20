import { useState } from 'react'

const ISO2 = /^[A-Za-z]{2}$/

interface Props {
  geos: string[]
  onChange: (geos: string[]) => void
}

/** Country chips. The server validates again; this only gives quick feedback. */
export default function GeoInput({ geos, onChange }: Props) {
  const [draft, setDraft] = useState('')
  const [invalid, setInvalid] = useState(false)

  function commit() {
    const code = draft.trim()
    if (!code) return
    if (!ISO2.test(code)) return setInvalid(true)
    const upper = code.toUpperCase()
    if (!geos.includes(upper)) onChange([...geos, upper])
    setDraft('')
    setInvalid(false)
  }

  return (
    <div className="field">
      <label htmlFor="geo">GEO sent to google.com</label>
      <div className={`chips${invalid ? ' invalid' : ''}`}>
        {geos.map((g) => (
          <span key={g} className="chip">
            {g}
            <button type="button" aria-label={`Remove ${g}`} onClick={() => onChange(geos.filter((x) => x !== g))}>×</button>
          </span>
        ))}
        <input id="geo" type="text" placeholder="Add country code" value={draft}
          aria-invalid={invalid} aria-describedby="geo-help"
          onChange={(e) => { setDraft(e.target.value); setInvalid(false) }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commit()
            }
          }} />
      </div>
      <span id="geo-help" className={invalid ? 'error-text' : 'hint'}>
        {invalid ? 'Use 2-letter ISO codes, e.g. AU.' : 'Type an ISO code and press Enter. Everyone else goes to the offer.'}
      </span>
    </div>
  )
}
