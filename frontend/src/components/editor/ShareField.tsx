import { useRef, useState } from 'react'

interface Props {
  offerId: number
  share: number
  disabled: boolean
  onCommit: (share: number) => void
}

function parse(draft: string): number | null {
  if (draft.trim() === '') return null
  const value = Math.round(Number(draft))
  return Number.isNaN(value) ? null : Math.max(0, Math.min(100, value))
}

/** Inline share edit (vision §5): Enter or blur applies, Escape cancels, unchanged does nothing. */
export default function ShareField({ offerId, share, disabled, onCommit }: Props) {
  const [draft, setDraft] = useState<string | null>(null)
  const closed = useRef(false) // Enter/Escape close the field, which may also blur it: apply once.

  function close(apply: boolean) {
    if (closed.current || draft === null) return
    closed.current = true
    setDraft(null)
    const value = apply ? parse(draft) : null
    if (value !== null && value !== share) onCommit(value)
  }

  if (draft === null) {
    return (
      <button type="button" className="share" disabled={disabled}
        aria-label={`Edit share of offer ${offerId}, currently ${share} percent`}
        onClick={() => { closed.current = false; setDraft(String(share)) }}>
        {share}%
      </button>
    )
  }
  return (
    <span className="share-edit">
      <input type="number" min={0} max={100} autoFocus value={draft} aria-label={`Share for offer ${offerId}`}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') close(true)
          if (e.key === 'Escape') close(false)
        }}
        onBlur={() => close(true)} />
      %
    </span>
  )
}
