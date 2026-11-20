import { useEffect, useState } from 'react'
import { api } from '../api/client'

type State = 'checking' | 'connected' | 'unreachable'

export default function ConnectionBadge() {
  const [state, setState] = useState<State>('checking')
  useEffect(() => {
    api.GET('/api/keitaro/ping').then(({ data }) => {
      setState((data as { reachable?: boolean } | undefined)?.reachable ? 'connected' : 'unreachable')
    }, () => setState('unreachable'))
  }, [])
  const label = { checking: 'Checking Keitaro…', connected: 'Keitaro connected', unreachable: 'Keitaro unreachable' }[state]
  return (
    <span className={`badge badge-${state}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  )
}
