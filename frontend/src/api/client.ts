import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

/** Typed client generated from the backend's OpenAPI schema (`npm run gen:api`). */
export const api = createClient<paths>({ baseUrl: '' })
export type Schemas = components['schemas']

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(errorMessage(body))
    this.status = status
    this.body = body
  }
}

type Detail = string | { message?: unknown } | { msg?: unknown }[]

/** The human message inside a FastAPI error body: string, Keitaro failure, or validation list. */
export function errorMessage(body: unknown): string {
  const detail = (body as { detail?: Detail } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => String(d.msg)).join('. ')
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  return 'Something went wrong.'
}

interface Outcome<T> {
  data?: T
  error?: unknown
  response: Response
}

/** Unwraps an openapi-fetch call: the data, or an ApiError. */
export async function call<T>(request: Promise<Outcome<T>>): Promise<T> {
  const { data, error, response } = await request
  if (error !== undefined || data === undefined) throw new ApiError(response.status, error)
  return data
}
