import { PERIODS, periodLabel, type PeriodKey } from './format'

interface Props {
  period: PeriodKey
  onPick: (period: PeriodKey) => void
  onRefresh: () => void
}

export default function PeriodSwitch({ period, onPick, onRefresh }: Props) {
  return (
    <div className="stats-bar">
      <div className="stats-period">
        <span id="period-l" className="muted small strong">Stats period</span>
        <div role="group" aria-labelledby="period-l" className="segmented">
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={p === period} onClick={() => onPick(p)}>{periodLabel(p)}</button>
          ))}
        </div>
      </div>
      <div className="muted small stats-source">
        <span>From Keitaro reports · beta</span>
        <button type="button" className="secondary icon" aria-label="Refresh stats" title="Refresh stats" onClick={onRefresh}>↻</button>
      </div>
    </div>
  )
}
