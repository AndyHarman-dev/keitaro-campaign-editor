import type { Schemas } from '../../api/client'
import { rowAction, rowTag } from './rowLabels'
import ShareField from './ShareField'
import type { OpIn } from './useEditor'

type Row = Schemas['RowView']

const ACTION_LABEL = { remove: 'Remove', bring_back: 'Bring back', forget: 'Remove' }

interface Props {
  row: Row
  onOp: (op: OpIn) => void
  onForget: (offerId: number) => void
}

export default function OfferRowView({ row, onOp, onForget }: Props) {
  const removed = row.status === 'removed'
  const tag = rowTag(row)
  const action = rowAction(row)
  const pinLabel = `${row.pinned ? 'Unpin' : 'Pin'} share of offer ${row.offer_id}`
  const act = () => (action === 'forget' ? onForget(row.offer_id) : onOp({ kind: action, offer_id: row.offer_id }))
  return (
    <div role="row" className={`offer-row${removed ? ' removed' : ''}${row.change ? ' changed' : ''}`}>
      <div role="cell" className="offer-cell">
        <div className="offer-name">
          <span className="mono muted">[{row.offer_id}]</span>
          {row.name ? <span className="name">{row.name}</span> : <span className="muted no-access">no access to this offer</span>}
          {tag && <span className={`tag tag-${tag.tone}`}>{tag.text}</span>}
        </div>
        {row.preview_url && <a href={row.preview_url} target="_blank" rel="noreferrer" className="small">preview</a>}
      </div>
      <div role="cell" className="share-cell">
        <ShareField offerId={row.offer_id} share={row.share} disabled={removed}
          onCommit={(share) => onOp({ kind: 'set_share', offer_id: row.offer_id, share })} />
        <button type="button" className={`pin${row.pinned ? ' on' : ''}`} disabled={removed}
          aria-pressed={row.pinned} aria-label={pinLabel} title={pinLabel}
          onClick={() => onOp({ kind: 'toggle_pin', offer_id: row.offer_id })}>📌</button>
      </div>
      <span role="cell" className="muted placeholder" aria-label="No stats yet">—</span>
      <span role="cell" className="muted placeholder" aria-label="No trends yet">—</span>
      <div role="cell" className="actions">
        <button type="button" className="secondary" onClick={act}>{ACTION_LABEL[action]}</button>
      </div>
    </div>
  )
}
