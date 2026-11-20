import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api, call, type Schemas } from '../../api/client'
import type { StatsReload } from '../stats/useStats'
import { SerialQueue, flowIn } from './serialQueue'

type View = Schemas['EditorView']
type Flow = Schemas['FlowView']
type Reply = Promise<{ data?: View; error?: unknown; response: Response }>
export type FlowProblem = Schemas['FlowProblem']
export type OpIn = Schemas['OpRequest']['op']

function problemOf(error: unknown): FlowProblem | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  return (error.body as { detail: FlowProblem }).detail
}

/** Fetch stays visibly busy at least this long, so a fast reply still reads as "it fetched". */
export const MIN_BUSY_MS = 400
const pause = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

const versionsOf = (view: View) => Object.fromEntries(view.flows.map((f) => [f.stream_id, f.version]))

/** Editor state: the backend's view, notes to show, and per-flow conflict/stale problems.
 *
 * Requests run one at a time, and each is built only when its turn comes, from the latest
 * view. A share edit applied on blur followed by a click on Push therefore sends the push
 * after the edit, with the version the edit produced. */
export function useEditor(campaignId: number) {
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [problems, setProblems] = useState<Record<number, FlowProblem>>({})
  const [fetching, setFetching] = useState(false)
  const [statsReload, setStatsReload] = useState<StatsReload>({ epoch: 0, refresh: false })
  // Stats reload after Fetch, Push and Push all, never after a share edit (vision V6).
  const reloadStats = useCallback(() => setStatsReload((r) => ({ epoch: r.epoch + 1, refresh: true })), [])
  const queue = useRef(new SerialQueue<View>()).current

  const run = useCallback(async (request: Reply, streamId?: number, clearsProblems = false) => {
    try {
      const next = await call(request)
      queue.current = next
      setView(next)
      setNotes(next.notes)
      setError(null)
      if (clearsProblems) setProblems({})
    } catch (e) {
      const problem = problemOf(e)
      if (problem && streamId !== undefined) setProblems((p) => ({ ...p, [streamId]: problem }))
      else setError(e instanceof Error ? e.message : String(e))
    }
  }, [queue])

  const enqueue = useCallback((build: (current: View | null) => Reply | null, streamId?: number, clearsProblems = false) =>
    queue.push(build, (request) => run(request, streamId, clearsProblems)), [queue, run])

  const path = { params: { path: { campaign_id: campaignId } } }
  const reload = useCallback(
    () => enqueue(() => api.GET('/api/campaigns/{campaign_id}/editor', { params: { path: { campaign_id: campaignId } } }), undefined, true),
    [enqueue, campaignId],
  )
  useEffect(() => { reload() }, [reload])

  /** A flow request built from the flow's current version; skipped if the flow is gone. */
  const onFlow = (flow: Flow, send: (current: Flow) => Reply) => enqueue((v) => {
    const current = flowIn(v, flow.stream_id)
    return current && send(current)
  }, flow.stream_id)
  const flowPath = (flow: Flow) => ({ params: { path: { stream_id: flow.stream_id } } })
  const all = (url: '/api/campaigns/{campaign_id}/push' | '/api/campaigns/{campaign_id}/cancel') =>
    enqueue((v) => v && api.POST(url, { ...path, body: { versions: versionsOf(v) } }))

  return {
    view, error, notes, problems, fetching, statsReload,
    dismissNotes: () => setNotes([]),
    reload,
    fetch: async () => {
      setFetching(true)
      await Promise.all([enqueue(() => api.POST('/api/campaigns/{campaign_id}/fetch', path), undefined, true), pause(MIN_BUSY_MS)])
      setFetching(false)
      reloadStats()
    },
    op: (flow: Flow, op: OpIn) =>
      onFlow(flow, (f) => api.POST('/api/flows/{stream_id}/ops', { ...flowPath(f), body: { version: f.version, op } })),
    forget: (flow: Flow, offerId: number) =>
      onFlow(flow, (f) => api.POST('/api/flows/{stream_id}/forget', { ...flowPath(f), body: { version: f.version, offer_id: offerId } })),
    push: (flow: Flow) =>
      onFlow(flow, (f) => api.POST('/api/flows/{stream_id}/push', { ...flowPath(f), body: { version: f.version } })).then(reloadStats),
    cancel: (flow: Flow) =>
      onFlow(flow, (f) => api.POST('/api/flows/{stream_id}/cancel', { ...flowPath(f), body: { version: f.version } })),
    pushAll: () => all('/api/campaigns/{campaign_id}/push').then(reloadStats),
    cancelAll: () => all('/api/campaigns/{campaign_id}/cancel'),
  }
}

export type Editor = ReturnType<typeof useEditor>
