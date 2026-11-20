import { useState } from 'react'
import type { Schemas } from '../../api/client'
import OfferPicker from '../OfferPicker'
import OfferRowView from './OfferRowView'
import { pendingLabel } from './rowLabels'
import type { FlowProblem, OpIn } from './useEditor'
import BusyButton from '../BusyButton'

type Flow = Schemas['FlowView']
type Offer = Schemas['OfferOut']

interface Props {
  flow: Flow
  problem: FlowProblem | undefined
  onOp: (op: OpIn) => void
  onForget: (offerId: number) => void
  onPush: () => void
  onCancel: () => void
  onFetch: () => void
  fetching: boolean
  onReload: () => void
}

function ProblemBanner({ problem, onFetch, fetching, onReload }: { problem: FlowProblem; onFetch: () => void; fetching: boolean; onReload: () => void }) {
  const conflict = problem.kind === 'conflict'
  return (
    <div role="alert" className="alert flow-alert">
      <div>
        <p className="strong">{problem.message}</p>
        <p>{conflict
          ? 'Push is blocked so nothing gets overwritten. Fetch merges Keitaro’s version; your pending edits stay on top.'
          : 'Your last action was not applied.'}</p>
      </div>
      {conflict
        ? <BusyButton className="primary" busy={fetching} busyLabel="Fetching…" onClick={onFetch}>Fetch & merge</BusyButton>
        : <button type="button" className="primary" onClick={onReload}>Reload</button>}
    </div>
  )
}

function AddOffer({ flow, onAdd }: { flow: Flow; onAdd: (offerId: number) => void }) {
  const [picked, setPicked] = useState<Offer | null>(null)
  const [round, setRound] = useState(0) // remounts the picker to clear it after an add
  return (
    <div className="add-offer">
      <OfferPicker key={round} id={`add-${flow.stream_id}`} label={`Add offer to ${flow.name}`}
        placeholder="Add offer — search by name or ID" onPick={setPicked} onClear={() => setPicked(null)} pickedLabel={(o) => `[${o.id}] ${o.name}`}
        exclude={flow.rows.map((r) => r.offer_id)} />
      <button type="button" className="secondary" disabled={!picked}
        onClick={() => { if (picked) onAdd(picked.id); setPicked(null); setRound((n) => n + 1) }}>Add</button>
    </div>
  )
}

export default function FlowSection({ flow, problem, onOp, onForget, onPush, onCancel, onFetch, fetching, onReload }: Props) {
  return (
    <section aria-label={flow.name} className={`flow${flow.dirty ? ' dirty' : ''}`}>
      <div className="flow-head">
        <div className="flow-title">
          <h2>{flow.name} <span className="mono muted">#{flow.stream_id}</span></h2>
          <span className="muted small">{flow.summary} · total {flow.total}%</span>
          {flow.dirty && <span className="tag tag-pending">{pendingLabel(flow.pending_count)}</span>}
        </div>
        {flow.dirty && (
          <div className="flow-actions">
            <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
            <button type="button" className="primary" disabled={problem !== undefined} onClick={onPush}>Push to KT</button>
          </div>
        )}
      </div>
      {problem && <ProblemBanner problem={problem} onFetch={onFetch} fetching={fetching} onReload={onReload} />}
      <div role="table" aria-label={`Offers in ${flow.name}`} className="offers">
        <div role="row" className="offer-row head">
          <span role="columnheader">Offer</span><span role="columnheader">Share</span>
          <span role="columnheader">Stats</span><span role="columnheader">Trends</span>
          <span role="columnheader" className="actions">Actions</span>
        </div>
        {flow.rows.map((r) => <OfferRowView key={r.offer_id} row={r} onOp={onOp} onForget={onForget} />)}
      </div>
      <AddOffer flow={flow} onAdd={(id) => onOp({ kind: 'add', offer_id: id })} />
    </section>
  )
}
