import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Schemas } from '../../api/client'
import type { PeriodKey } from './format'

export type StatsData = Schemas['StatsOk']
export type StatsState =
  | { status: 'loading' }
  | { status: 'disabled' }
  | { status: 'unavailable'; reason: string }
  | { status: 'ok'; data: StatsData }

/** When the editor wants fresh numbers: `epoch` goes up after Fetch, Push and Push all, and
 * `refresh` makes that request skip the backend's 60 s cache (plan P6). */
export interface StatsReload { epoch: number; refresh: boolean }

const FAILED = 'the stats request failed'

/** Stats beside the editor (vision V6): loaded on their own, never blocking an edit. A reply
 * for an older (campaign, period, epoch) is dropped, so a fast period switch never shows
 * stale numbers. */
export function useStats(campaignId: number, period: PeriodKey, reload: StatsReload) {
  // Until the first reply, look exactly like the beta is off: no skeleton flashes when it is.
  const [state, setState] = useState<StatsState>({ status: 'disabled' })
  const [retries, setRetries] = useState(0)
  const served = useRef({ epoch: reload.epoch, retries: 0 })

  useEffect(() => {
    const fresh = (reload.refresh && served.current.epoch !== reload.epoch) || served.current.retries !== retries
    served.current = { epoch: reload.epoch, retries }
    let live = true
    setState((s) => (s.status === 'disabled' ? s : { status: 'loading' }))
    api.GET('/api/campaigns/{campaign_id}/stats', {
      params: { path: { campaign_id: campaignId }, query: { period, refresh: fresh } },
    }).then(({ data, response }) => {
      if (!live) return
      if (!response.ok || data === undefined) setState({ status: 'unavailable', reason: FAILED })
      else setState(data.status === 'ok' ? { status: 'ok', data } : data)
    }, () => { if (live) setState({ status: 'unavailable', reason: FAILED }) })
    return () => { live = false }
  }, [campaignId, period, reload.epoch, reload.refresh, retries])

  const retry = useCallback(() => setRetries((n) => n + 1), [])
  return { state, retry }
}
