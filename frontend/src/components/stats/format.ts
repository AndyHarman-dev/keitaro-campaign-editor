import type { Schemas } from '../../api/client'

/** Display only: the backend computes every number (plan P5); this file only formats them. */

export type Cell = Schemas['CellOut']
export type Trend = Schemas['TrendOut']
export type PeriodKey = Schemas['StatsOk']['period']

export const PERIODS: PeriodKey[] = ['today', '7', '14', '30']

export const periodLabel = (p: PeriodKey) => (p === 'today' ? 'Today' : `${p} days`)

export function money(value: string | null, currency: string): string {
  return value === null ? '—' : `${currency}${Number(value).toFixed(2)}`
}

export function percent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

const clicksText = (n: number) => n.toLocaleString('en-US')

export const noClicksLabel = (p: PeriodKey) => (p === 'today' ? 'No clicks today' : `No clicks in ${p} days`)

/** "18% still pending"; on Today, "today: mostly pending (90% still pending)".
 * Empty with no postbacks, or when nothing rounds to a whole percent still pending. */
export function pendingLabel(cell: Cell, p: PeriodKey): string {
  const rounded = cell.pending === null ? 0 : Math.round(cell.pending * 100)
  if (rounded === 0) return ''
  const share = `${rounded}% still pending`
  return p === 'today' ? `today: mostly pending (${share})` : share
}

export function cellLines(cell: Cell, currency: string): { primary: string; secondary: string } {
  return {
    primary: `EPC ${money(cell.epc, currency)}`,
    secondary: `${clicksText(cell.clicks)} clicks · CR ${percent(cell.cr)}`,
  }
}

export function observedLabel(cell: Cell): string {
  return cell.split === null ? '' : `${Math.round(cell.split * 100)}% of this flow's clicks went here`
}

export function totalsLabel(cell: Cell, p: PeriodKey, currency: string): string {
  return `${periodLabel(p)}: ${clicksText(cell.clicks)} clicks · CR ${percent(cell.cr)} · EPC ${money(cell.epc, currency)}`
}

const pct = (x: number) => `${Math.round(Math.abs(x) * 100)}%`
const signed = (x: number) => `${x >= 0 ? '+' : '−'}${pct(x)}`

export type Direction = 'up' | 'down' | 'noise'

export function direction(t: Trend): Direction | null {
  if (t.verdict === 'not_enough_traffic') return null
  return t.verdict === 'within_noise' ? 'noise' : t.verdict
}

/** "+42%", "−44%", or "within noise". */
export function deltaLabel(t: Trend): string {
  const dir = direction(t)
  if (dir === null || t.change === null) return ''
  return dir === 'noise' ? 'within noise' : signed(t.change)
}

/** "80 → 72 conv." plus "(−17%, band ±32%)" when the change is within noise. */
export function convLabel(t: Trend): string {
  if (t.change === null || t.band === null) return ''
  const base = `${t.older.conversions} → ${t.newer.conversions} conv.`
  return t.verdict === 'within_noise' ? `${base} (${signed(t.change)}, band ±${pct(t.band)})` : base
}

export function trendAria(t: Trend, currency: string): string {
  if (t.change === null) return 'Trend: not enough traffic'
  const verdict = t.verdict === 'within_noise' ? `change ${signed(t.change)} is within noise`
    : `${t.verdict} ${pct(t.change)}`
  return `EPC days 3 to 9 ago ${money(t.newer.epc, currency)} versus ${money(t.older.epc, currency)} the week before, ` +
    `on ${t.newer.conversions} versus ${t.older.conversions} conversions: ${verdict}`
}

/** Sparkline points (84 × 26 box); the last two days, still filling in, go in `tail`. */
export function sparkline(daily: (string | null)[]): { main: string; tail: string } {
  const values = daily.map((v) => (v === null ? null : Number(v)))
  const known = values.filter((v): v is number => v !== null)
  const hi = known.length ? Math.max(...known) : 1
  const lo = known.length ? Math.min(...known) : 0
  const point = (v: number | null, i: number) =>
    v === null ? null : `${(i * 6 + 3).toFixed(1)},${(23 - ((v - lo) / (hi - lo || 1)) * 20).toFixed(1)}`
  const points = values.map(point)
  const join = (list: (string | null)[]) => list.filter(Boolean).join(' ')
  // Days −14…−3 solid; the lighter tail runs from day −3 through −2 and −1.
  return { main: join(points.slice(0, 12)), tail: join(points.slice(11)) }
}
