import { PERIODS, type PeriodKey } from './format'

const KEY = 'stats-period'

/** The remembered period; storage may be missing or throw (private windows), so 7 days then. */
export function loadPeriod(): PeriodKey {
  try {
    const saved = globalThis.localStorage?.getItem(KEY)
    return PERIODS.find((p) => p === saved) ?? '7'
  } catch {
    return '7'
  }
}

export function savePeriod(period: PeriodKey): void {
  try {
    globalThis.localStorage?.setItem(KEY, period)
  } catch {
    // Remembering the period is a convenience; the switch still works without it.
  }
}
