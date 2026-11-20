import type { Schemas } from '../api/client'

type Row = Schemas['RowView']
type Flow = Schemas['FlowView']
type View = Schemas['EditorView']

export function row(offer_id: number, share: number, extra: Partial<Row> = {}): Row {
  return {
    offer_id, name: `Offer ${offer_id}`, share, pinned: false, status: 'active', removed_by: null,
    archived: false, change: null, base_share: share, preview_url: null, ...extra,
  }
}

export function flow(extra: Partial<Flow> = {}): Flow {
  const rows = extra.rows ?? [row(3749, 34), row(3717, 33), row(11111, 33)]
  return {
    stream_id: 1001, name: 'Flow 2', type: 'regular', position: 2, summary: 'regular · position 2',
    has_offers: rows.length > 0, version: 3, dirty: false, pending_count: 0,
    total: rows.filter((r) => r.status === 'active').reduce((s, r) => s + r.share, 0), rows, ...extra,
  }
}

export const forced: Flow = {
  stream_id: 1000, name: 'Flow 1', type: 'forced', position: 1,
  summary: 'forced · country in AU → https://google.com', has_offers: false, version: 1,
  dirty: false, pending_count: 0, total: 0, rows: [],
}

export function view(flows: Flow[] = [forced, flow()], extra: Partial<View> = {}): View {
  return {
    campaign: { id: 216250, name: 'RO beauty — spring' }, kt_url: 'https://tracker.example/admin/#!/campaigns/216250',
    fetched_at: '2026-11-20T12:00:00Z', flows, notes: [], ...extra,
  }
}
