import type { Schemas } from '../../api/client'
import {
  cellLines, convLabel, deltaLabel, direction, noClicksLabel, observedLabel, pendingLabel, sparkline,
  trendAria, type PeriodKey,
} from './format'
import type { StatsState } from './useStats'

export type OfferStats = Schemas['OfferStatsOut']

/** What a row's two stats cells need: the overall state and this row's entry, if any. */
export interface RowStats {
  state: StatsState
  offer: OfferStats | undefined
  isNew: boolean
}

const Placeholder = ({ label }: { label: string }) => (
  <span role="cell" className="muted placeholder" aria-label={label}>—</span>
)

const Note = ({ text }: { text: string }) => <span role="cell" className="muted small">{text}</span>

export function StatsCell({ stats, period }: { stats: RowStats; period: PeriodKey }) {
  const { state, offer, isNew } = stats
  if (state.status === 'disabled') return <Placeholder label="No stats yet" />
  if (state.status === 'loading') return <span role="cell" className="skeleton" aria-label="Loading stats" />
  if (state.status === 'unavailable') return <Placeholder label="Stats unavailable" />
  if (isNew) return <Note text="New: no traffic yet" />
  if (!offer || offer.cell.clicks === 0) return <Note text={noClicksLabel(period)} />
  const { primary, secondary } = cellLines(offer.cell, state.data.currency)
  const pending = pendingLabel(offer.cell, period)
  return (
    <div role="cell" className="stats-cell">
      <span className="stat-primary">{primary}</span>
      <span className="small muted">{secondary}</span>
      <span className="tiny muted">{observedLabel(offer.cell)}</span>
      {pending && <span className="tiny pending-text">{pending}</span>}
    </div>
  )
}

const ARROW = { up: '▲', down: '▼', noise: '–' }

export function TrendCell({ stats }: { stats: RowStats }) {
  const { state, offer, isNew } = stats
  if (state.status === 'disabled') return <Placeholder label="No trends yet" />
  if (state.status === 'loading') return <span role="cell" className="skeleton" aria-label="Loading trend" />
  if (state.status === 'unavailable') return <Placeholder label="Trend unavailable" />
  if (isNew) return <Note text="—" />
  const dir = offer ? direction(offer.trend) : null
  if (!offer || dir === null) return <Note text="Not enough traffic" />
  const { main, tail } = sparkline(offer.trend.daily_epc)
  return (
    <div role="cell" className={`trend-cell trend-${dir}`}>
      <svg width="84" height="26" viewBox="0 0 84 26" role="img" aria-label={trendAria(offer.trend, state.data.currency)}>
        <polyline points={main} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
        <polyline points={tail} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" opacity="0.35" />
      </svg>
      <div className="trend-text">
        <span className="delta"><span aria-hidden="true">{ARROW[dir]} </span>{deltaLabel(offer.trend)}</span>
        <span className="tiny muted">{convLabel(offer.trend)}</span>
      </div>
    </div>
  )
}
