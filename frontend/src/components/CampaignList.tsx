import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, call, type Schemas } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'

type Campaign = Schemas['CampaignOut']

export default function CampaignList() {
  const [query, setQuery] = useState('')
  const [refreshes, setRefreshes] = useState(0)
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const q = useDebounced(query)

  useEffect(() => {
    let current = true
    call(api.GET('/api/campaigns', { params: { query: { q } } })).then(
      (data) => current && (setCampaigns(data), setError(null)),
      (e: Error) => current && setError(e.message),
    )
    return () => {
      current = false
    }
  }, [q, refreshes])

  return (
    <section aria-labelledby="camps" className="panel">
      <div className="panel-head">
        <div>
          <h1 id="camps">Campaigns</h1>
          <p className="muted">Open a campaign to edit the offers in its flows.</p>
        </div>
        <div className="search">
          <label htmlFor="q" className="sr-only">Search campaigns</label>
          <input id="q" type="search" placeholder="Search by name or ID" value={query}
            onChange={(e) => setQuery(e.target.value)} />
          <button type="button" className="icon-button" aria-label="Refresh from Keitaro"
            onClick={() => setRefreshes((n) => n + 1)}>↻</button>
        </div>
      </div>
      {error && <p role="status" className="error-text">{error}</p>}
      <div className="table campaigns">
        <div className="table-head"><span>ID</span><span>Name</span><span>Group</span><span>Domain</span></div>
        {campaigns?.map((c) => (
          <Link key={c.id} to={`/campaigns/${c.id}`} className="table-row">
            <span className="mono muted">{c.id}</span>
            <span className="strong">{c.name}</span>
            <span className="muted">{c.group ?? '—'}</span>
            <span className="muted">{c.domain ?? '—'}</span>
          </Link>
        ))}
        {campaigns?.length === 0 && <p className="empty">No campaigns match “{q}”.</p>}
      </div>
    </section>
  )
}
