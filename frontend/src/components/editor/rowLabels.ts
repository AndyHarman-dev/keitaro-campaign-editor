import type { Schemas } from '../../api/client'

type Row = Schemas['RowView']

export type Tone = 'pending' | 'neutral' | 'danger'

/** The small tag next to an offer's name, if any. */
export function rowTag(row: Row): { text: string; tone: Tone } | null {
  if (row.archived) return { text: 'archived in Keitaro · can’t be restored', tone: 'danger' }
  switch (row.change) {
    case 'added': return { text: 'new', tone: 'pending' }
    case 'restored': return { text: 'will be restored', tone: 'pending' }
    case 'removed': return { text: 'will be removed', tone: 'pending' }
    case 'share': return { text: `was ${row.base_share}%`, tone: 'pending' }
  }
  if (row.removed_by === 'keitaro') return { text: 'removed in Keitaro', tone: 'neutral' }
  return null
}

export type RowAction = 'remove' | 'bring_back' | 'forget'

/** Active rows can be removed; removed rows come back, unless the offer is archived. */
export function rowAction(row: Row): RowAction {
  if (row.archived) return 'forget'
  return row.status === 'active' ? 'remove' : 'bring_back'
}

export function pendingLabel(count: number): string {
  return `${count} pending change${count === 1 ? '' : 's'}`
}
