import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import AllOffersPanel from '../components/editor/AllOffersPanel'
import FlowSection from '../components/editor/FlowSection'
import { useEditor, type Editor } from '../components/editor/useEditor'
import type { Schemas } from '../api/client'

function TopActions({ editor, allOpen, onToggleAll }: { editor: Editor; allOpen: boolean; onToggleAll: () => void }) {
  const view = editor.view!
  const dirty = view.flows.filter((f) => f.dirty).length
  return (
    <div className="top-actions">
      <button type="button" className="secondary" aria-expanded={allOpen} aria-controls="all-offers" onClick={onToggleAll}>
        {allOpen ? 'Hide all offers' : 'Show all offers'}
      </button>
      <a href={view.kt_url} target="_blank" rel="noreferrer" className="secondary link-button">View in KT</a>
      {dirty > 0 ? (
        <>
          <button type="button" className="secondary" onClick={editor.cancelAll}>Cancel all</button>
          <button type="button" className="primary" onClick={editor.pushAll}>Push all to KT ({dirty})</button>
        </>
      ) : (
        <button type="button" className="primary" disabled={editor.fetching} aria-busy={editor.fetching} onClick={editor.fetch}>
          {editor.fetching ? <><span className="spinner" aria-hidden="true" />Fetching…</> : 'Fetch from KT'}
        </button>
      )}
    </div>
  )
}

function Notes({ notes, onDismiss }: { notes: string[]; onDismiss: () => void }) {
  return (
    <div role="status" aria-live="polite">
      {notes.length > 0 && (
        <div className="toast">
          <span>{notes.join(' ')}</span>
          <button type="button" aria-label="Dismiss" onClick={onDismiss}>×</button>
        </div>
      )}
    </div>
  )
}

function FlowsWithoutOffers({ flows }: { flows: Schemas['FlowView'][] }) {
  if (flows.length === 0) return null
  return (
    <section aria-label="Flows without offers" className="panel">
      <h2>Flows without offers</h2>
      {flows.map((f) => (
        <p key={f.stream_id}><span className="strong">{f.name}</span> <span className="mono muted">#{f.stream_id}</span> <span className="muted">· {f.summary}</span></p>
      ))}
    </section>
  )
}

export default function EditorScreen() {
  const campaignId = Number(useParams().id)
  const editor = useEditor(campaignId)
  const [allOpen, setAllOpen] = useState(false)
  const { view } = editor
  const withOffers = view?.flows.filter((f) => f.has_offers) ?? []
  const without = view?.flows.filter((f) => !f.has_offers) ?? []

  return (
    <div className="page">
      <header className="topbar">
        <Link to="/">← Campaigns</Link>
        <span className="brand">Campaign Editor</span>
      </header>
      <main className="editor">
        {editor.error && <div role="alert" className="alert">{editor.error}</div>}
        {view && (
          <>
            <div className="editor-head">
              <div>
                <h1>{view.campaign.name}</h1>
                <p className="muted small"><span className="mono">#{view.campaign.id}</span>
                  {view.fetched_at && ` · fetched ${new Date(view.fetched_at).toLocaleString()}`}</p>
              </div>
              <TopActions editor={editor} allOpen={allOpen} onToggleAll={() => setAllOpen((o) => !o)} />
            </div>
            <Notes notes={editor.notes} onDismiss={editor.dismissNotes} />
            {allOpen && <AllOffersPanel flows={withOffers} onAdd={(f, id) => editor.op(f, { kind: 'add', offer_id: id })} />}
            {withOffers.map((f) => (
              <FlowSection key={f.stream_id} flow={f} problem={editor.problems[f.stream_id]}
                onOp={(op) => editor.op(f, op)} onForget={(id) => editor.forget(f, id)}
                onPush={() => editor.push(f)} onCancel={() => editor.cancel(f)}
                onFetch={editor.fetch} onReload={editor.reload} />
            ))}
            <FlowsWithoutOffers flows={without} />
            <p className="muted small">Nothing is written to Keitaro until you push. Pinned shares never change on add or remove; unpinned offers split the rest equally. Removing a pinned offer hides its pin; Bring back restores it.</p>
          </>
        )}
      </main>
    </div>
  )
}
