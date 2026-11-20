import { useEffect, useState } from 'react'
import { api, call, type Schemas } from '../../api/client'
import { useDebounced } from '../../hooks/useDebounced'

type Flow = Schemas['FlowView']
type Offer = Schemas['OfferOut']

interface Props {
  flows: Flow[] // flows that hold offers
  onAdd: (flow: Flow, offerId: number) => void
}

/** Every offer this API key can read, with where it already is (vision §5 "Show all offers"). */
export default function AllOffersPanel({ flows, onAdd }: Props) {
  const [query, setQuery] = useState('')
  const [offers, setOffers] = useState<Offer[]>([])
  const q = useDebounced(query, 200)

  useEffect(() => {
    let current = true
    call(api.GET('/api/offers', { params: { query: { q } } })).then((data) => current && setOffers(data), () => current && setOffers([]))
    return () => {
      current = false
    }
  }, [q])

  return (
    <section aria-labelledby="all-h" id="all-offers" className="panel">
      <div>
        <h2 id="all-h">All offers in Keitaro <span className="muted">({offers.length})</span></h2>
        <span className="muted small">Every offer this API key can see. Archived offers are not listed.</span>
      </div>
      <label htmlFor="all-q" className="sr-only">Search all offers</label>
      <input id="all-q" type="search" placeholder="Search by name or ID" value={query} onChange={(e) => setQuery(e.target.value)} />
      <ul className="all-offers">
        {offers.map((o) => {
          const holding = flows.filter((f) => f.rows.some((r) => r.offer_id === o.id))
          return (
            <li key={o.id} aria-label={`[${o.id}] ${o.name}`}>
              <span className="mono muted">{o.id}</span>
              <span className="name">{o.name}</span>
              {holding.map((f) => <span key={f.stream_id} className="tag tag-info">in {f.name}</span>)}
              {flows.filter((f) => !holding.includes(f)).map((f) => (
                <button key={f.stream_id} type="button" className="secondary" onClick={() => onAdd(f, o.id)}>Add to {f.name}</button>
              ))}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
