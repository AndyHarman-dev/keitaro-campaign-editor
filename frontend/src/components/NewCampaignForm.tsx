import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, call, type Schemas } from '../api/client'
import AdvancedChoices from './AdvancedChoices'
import { resolveIds, useCreateCampaign, type Problem } from './createCampaign'
import GeoInput from './GeoInput'
import OfferPicker from './OfferPicker'

type Lookups = Schemas['LookupsOut']
type Offer = Schemas['OfferOut']
type Ids = Schemas['Defaults']

const NONE: Ids = { domain_id: null, group_id: null, source_id: null }

function Preview({ geos, offer }: { geos: string[]; offer: Offer | null }) {
  return (
    <section aria-label="Will create" className="preview">
      <span className="muted">Will create</span>
      <div><span className="strong">Flow 1</span> <span className="muted">forced · country in</span> <span className="mono">{geos.join(', ') || '—'}</span> <span className="muted">→ google.com</span></div>
      <div><span className="strong">Flow 2</span> <span className="muted">regular →</span> <span>{offer ? `[${offer.id}] ${offer.name}` : '—'}</span> <span className="mono">100%</span></div>
    </section>
  )
}

function ProblemAlert({ problem }: { problem: Problem }) {
  return (
    <div role="alert" className="alert">
      <p className="strong">{problem.title}</p>
      <p>{problem.message}{problem.note ? ` ${problem.note}` : ''}</p>
    </div>
  )
}

export default function NewCampaignForm() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [geos, setGeos] = useState<string[]>([])
  const [offer, setOffer] = useState<Offer | null>(null)
  const [lookups, setLookups] = useState<Lookups | null>(null)
  const [overrides, setOverrides] = useState<Ids>(NONE)
  const [key] = useState(() => crypto.randomUUID())
  const { busy, problem, create } = useCreateCampaign((id) => navigate(`/campaigns/${id}`))

  useEffect(() => {
    call(api.GET('/api/lookups')).then(setLookups, () => setLookups(null))
  }, [])

  const ready = name.trim() !== '' && geos.length > 0 && offer !== null && !busy
  const submit = () => offer && create({
    name, geos, offer_id: offer.id, idempotency_key: key,
    ...resolveIds(overrides, lookups?.defaults ?? NONE),
  })

  return (
    <section aria-labelledby="newc" className="panel form">
      <div>
        <h2 id="newc">New campaign</h2>
        <p className="muted">Creates the campaign in Keitaro with two flows.</p>
      </div>
      <div className="field">
        <label htmlFor="cname">Name</label>
        <input id="cname" type="text" placeholder="e.g. RO beauty — spring" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <GeoInput geos={geos} onChange={setGeos} />
      <OfferPicker id="offer" label="Offer" placeholder="Search offers by name or ID" onPick={setOffer} onClear={() => setOffer(null)}
        pickedLabel={(o) => `[${o.id}] ${o.name}`} />
      <AdvancedChoices lookups={lookups} overrides={overrides} onChange={setOverrides} />
      <Preview geos={geos} offer={offer} />
      {problem && <ProblemAlert problem={problem} />}
      <button type="button" className="primary" disabled={!ready} onClick={submit}>
        {busy ? 'Creating…' : 'Create in Keitaro'}
      </button>
    </section>
  )
}
