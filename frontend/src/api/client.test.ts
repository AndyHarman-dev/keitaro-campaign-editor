import { describe, expect, it } from 'vitest'
import { ApiError, call, errorMessage } from './client'

const response = (status: number) => new Response(null, { status })

describe('errorMessage', () => {
  it('reads a plain string detail', () => {
    expect(errorMessage({ detail: 'Choose a group under Advanced.' })).toBe('Choose a group under Advanced.')
  })
  it('reads a Keitaro failure', () => {
    expect(errorMessage({ detail: { message: 'Alias is taken', keitaro_status: 400, archived_campaign: false } }))
      .toBe('Alias is taken')
  })
  it('joins validation messages', () => {
    expect(errorMessage({ detail: [{ msg: 'Value error, use 2-letter ISO codes' }, { msg: 'Field required' }] }))
      .toBe('Value error, use 2-letter ISO codes. Field required')
  })
  it('falls back to a generic message', () => {
    expect(errorMessage(undefined)).toBe('Something went wrong.')
    expect(errorMessage({ detail: 42 })).toBe('Something went wrong.')
  })
})

describe('call', () => {
  it('returns data on success', async () => {
    await expect(call(Promise.resolve({ data: [1], response: response(200) }))).resolves.toEqual([1])
  })
  it('throws an ApiError with status, message and the raw body', async () => {
    const body = { detail: { message: 'Flow changed', keitaro_status: 0, archived_campaign: false } }
    const err = (await call(Promise.resolve({ error: body, response: response(409) })).catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.message).toBe('Flow changed')
    expect(err.body).toBe(body)
  })
  it('treats a missing body on success as an error', async () => {
    const err = await call(Promise.resolve({ response: response(204) })).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
  })
})
