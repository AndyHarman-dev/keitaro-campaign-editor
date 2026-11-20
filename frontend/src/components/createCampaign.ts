import { useState } from 'react'
import { ApiError, api, call, type Schemas } from '../api/client'

type Failure = Schemas['KeitaroFailure']
type Ids = Schemas['Defaults']

export interface Problem {
  title: string
  message: string
  note: string | null
}

const GENERIC = 'Could not create the campaign.'

function keitaroProblem(failure: Failure): Problem {
  return {
    title: 'Keitaro rejected the campaign.',
    message: failure.message,
    note: failure.archived_campaign
      ? 'The flows failed after the campaign was created, so it was archived. You can retry.'
      : 'Nothing was created.',
  }
}

/** What to tell the user about a failed create. */
export function describeFailure(error: unknown): Problem {
  if (!(error instanceof ApiError)) {
    return { title: GENERIC, message: error instanceof Error ? error.message : String(error), note: null }
  }
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  if (error.status === 502 && detail && typeof detail === 'object') return keitaroProblem(detail as Failure)
  return { title: GENERIC, message: error.message, note: null }
}

/** Each Advanced choice wins over its .env default. */
export function resolveIds(overrides: Ids, defaults: Ids): Ids {
  return {
    domain_id: overrides.domain_id ?? defaults.domain_id,
    group_id: overrides.group_id ?? defaults.group_id,
    source_id: overrides.source_id ?? defaults.source_id,
  }
}

type Body = Schemas['CreateCampaignIn']

export function useCreateCampaign(onCreated: (campaignId: number) => void) {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)

  async function create(body: Body) {
    setBusy(true)
    setProblem(null)
    try {
      onCreated((await call(api.POST('/api/campaigns', { body }))).campaign_id)
    } catch (error) {
      setProblem(describeFailure(error))
      setBusy(false)
    }
  }

  return { busy, problem, create }
}
