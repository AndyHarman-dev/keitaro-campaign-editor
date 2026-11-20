import { vi } from 'vitest'

export interface Call {
  method: string
  path: string
  query: URLSearchParams
  body: unknown
}

type Answer = { status?: number; body: unknown }
type Reply = Answer | ((call: Call) => Answer | Promise<Answer>)

/** Stubs fetch with "METHOD /path" routes; records every call. Unknown routes answer 404. */
export function mockApi(routes: Record<string, Reply>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(String(input), init)
    const url = new URL(request.url, 'http://localhost')
    const text = await request.text()
    const call = { method: request.method, path: url.pathname, query: url.searchParams, body: text ? JSON.parse(text) : undefined }
    calls.push(call)
    const route = routes[`${call.method} ${call.path}`]
    const reply = typeof route === 'function' ? await route(call) : route
    if (!reply) return new Response(JSON.stringify({ detail: 'not mocked' }), { status: 404 })
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, of: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key) }
}
