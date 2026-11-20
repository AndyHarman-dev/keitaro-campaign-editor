import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, call, type Schemas } from '../../api/client'

type View = Schemas['EditorView']
type Flow = Schemas['FlowView']
export type FlowProblem = Schemas['FlowProblem']
export type OpIn = Schemas['OpRequest']['op']

function problemOf(error: unknown): FlowProblem | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  return (error.body as { detail: FlowProblem }).detail
}

const versionsOf = (view: View) => Object.fromEntries(view.flows.map((f) => [f.stream_id, f.version]))

/** Editor state: the backend's view, notes to show, and per-flow conflict/stale problems. */
export function useEditor(campaignId: number) {
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [problems, setProblems] = useState<Record<number, FlowProblem>>({})

  const run = useCallback(async (request: Promise<{ data?: View; error?: unknown; response: Response }>,
    streamId?: number, clearsProblems = false) => {
    try {
      const next = await call(request)
      setView(next)
      setNotes(next.notes)
      setError(null)
      if (clearsProblems) setProblems({})
    } catch (e) {
      const problem = problemOf(e)
      if (problem && streamId !== undefined) setProblems((p) => ({ ...p, [streamId]: problem }))
      else setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const path = { params: { path: { campaign_id: campaignId } } }
  const reload = useCallback(
    () => run(api.GET('/api/campaigns/{campaign_id}/editor', { params: { path: { campaign_id: campaignId } } }), undefined, true),
    [run, campaignId],
  )
  useEffect(() => { reload() }, [reload])

  const flowPath = (flow: Flow) => ({ params: { path: { stream_id: flow.stream_id } } })
  return {
    view, error, notes, problems,
    dismissNotes: () => setNotes([]),
    reload,
    fetch: () => run(api.POST('/api/campaigns/{campaign_id}/fetch', path), undefined, true),
    op: (flow: Flow, op: OpIn) =>
      run(api.POST('/api/flows/{stream_id}/ops', { ...flowPath(flow), body: { version: flow.version, op } }), flow.stream_id),
    forget: (flow: Flow, offerId: number) =>
      run(api.POST('/api/flows/{stream_id}/forget', { ...flowPath(flow), body: { version: flow.version, offer_id: offerId } }), flow.stream_id),
    push: (flow: Flow) =>
      run(api.POST('/api/flows/{stream_id}/push', { ...flowPath(flow), body: { version: flow.version } }), flow.stream_id),
    cancel: (flow: Flow) =>
      run(api.POST('/api/flows/{stream_id}/cancel', { ...flowPath(flow), body: { version: flow.version } }), flow.stream_id),
    pushAll: () => view && run(api.POST('/api/campaigns/{campaign_id}/push', { ...path, body: { versions: versionsOf(view) } })),
    cancelAll: () => view && run(api.POST('/api/campaigns/{campaign_id}/cancel', { ...path, body: { versions: versionsOf(view) } })),
  }
}

export type Editor = ReturnType<typeof useEditor>
