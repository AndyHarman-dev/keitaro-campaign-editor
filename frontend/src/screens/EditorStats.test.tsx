import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../api/client'
import { flow, forced, row, view } from '../test/editorFixture'
import { mockApi, type Call } from '../test/mockApi'
import EditorScreen from './EditorScreen'

type Cell = Schemas['CellOut']
type Trend = Schemas['TrendOut']

const STATS = 'GET /api/campaigns/216250/stats'

const cell = (clicks: number, over: Partial<Cell> = {}): Cell => ({
  clicks, leads: 2, sales: 8, rejected: 0, conversions: 10, revenue: '50.0000', epc: '0.5000',
  cr: 0.1, pending: 0.2, split: 0.5, ...over,
})
const thin: Trend = {
  verdict: 'not_enough_traffic', daily_epc: Array(14).fill(null),
  older: { clicks: 10, conversions: 0, epc: null }, newer: { clicks: 10, conversions: 0, epc: null }, change: null, band: null,
}
const down: Trend = {
  verdict: 'down', daily_epc: Array.from({ length: 14 }, (_, i) => String(1 - i / 20)),
  older: { clicks: 9000, conversions: 300, epc: '0.6000' }, newer: { clicks: 9000, conversions: 180, epc: '0.3400' },
  change: -0.44, band: 0.19,
}

function ok(period = '7', clicks = 100) {
  return {
    status: 'ok', period, as_of: '2026-11-20', timezone: 'UTC', currency: '$',
    flows: [{
      stream_id: 1001, totals: cell(clicks * 2, { split: null, epc: '0.2500' }),
      offers: [
        { offer_id: 3749, cell: cell(clicks), trend: down },
        { offer_id: 3717, cell: cell(0, { cr: null, epc: null, pending: null, split: 0 }), trend: thin },
      ],
    }],
  }
}

function routes(extra = {}) {
  return mockApi({
    'GET /api/campaigns/216250/editor': { body: view([forced, flow({ rows: [row(3749, 34), row(3717, 33), row(11111, 33, { change: 'added' })] })]) },
    [STATS]: ({ query }: Call) => ({ body: ok(query.get('period')!) }),
    ...extra,
  })
}

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={['/campaigns/216250']}>
      <Routes><Route path="/campaigns/:id" element={<EditorScreen />} /></Routes>
    </MemoryRouter>,
  )
}

const rowOf = (id: number) => screen.getByRole('row', { name: new RegExp(`\\[${id}\\]`) })
const statsCalls = (api: ReturnType<typeof mockApi>) => api.of(STATS).map((c) => `${c.query.get('period')}/${c.query.get('refresh')}`)

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('stats beta on', () => {
  it('shows numbers, the trend, the flow totals and the row states', async () => {
    routes()
    renderEditor()
    const offer = await screen.findByRole('row', { name: /\[3749\]/ })
    expect(await within(offer).findByText('EPC $0.50')).toBeInTheDocument()
    expect(within(offer).getByText('100 clicks · CR 10.0%')).toBeInTheDocument()
    expect(within(offer).getByText("50% of this flow's clicks went here")).toBeInTheDocument()
    expect(within(offer).getByText('20% still pending')).toBeInTheDocument()
    expect(within(offer).getByText('−44%')).toBeInTheDocument()
    expect(within(offer).getByText('300 → 180 conv.')).toBeInTheDocument()
    expect(within(offer).getByRole('img', { name: /: down 44%$/ })).toBeInTheDocument()
    expect(within(rowOf(3717)).getByText('No clicks in 7 days')).toBeInTheDocument()
    expect(within(rowOf(3717)).getByText('Not enough traffic')).toBeInTheDocument()
    expect(within(rowOf(11111)).getByText('New: no traffic yet')).toBeInTheDocument()
    expect(screen.getByText('7 days: 200 clicks · CR 10.0% · EPC $0.25')).toBeInTheDocument()
    expect(screen.queryByLabelText('No stats yet')).not.toBeInTheDocument()
  })

  it('switches the period, remembers it, and reloads without skipping the cache', async () => {
    const api = routes()
    const user = userEvent.setup()
    renderEditor()
    await screen.findByText('7 days: 200 clicks · CR 10.0% · EPC $0.25')
    expect(screen.getByRole('button', { name: '7 days' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Today' }))
    expect(await screen.findByText(/^Today: 200 clicks/)).toBeInTheDocument()
    expect(within(rowOf(3749)).getByText('today: mostly pending (20% still pending)')).toBeInTheDocument()
    expect(localStorage.getItem('stats-period')).toBe('today')
    expect(statsCalls(api)).toEqual(['7/false', 'today/false'])
  })

  it('starts on the remembered period', async () => {
    localStorage.setItem('stats-period', '30')
    const api = routes()
    renderEditor()
    await screen.findByText(/^30 days: /)
    expect(statsCalls(api)).toEqual(['30/false'])
  })

  it('still works when storage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    routes()
    const user = userEvent.setup()
    renderEditor()
    await screen.findByText(/^7 days: /)
    await user.click(screen.getByRole('button', { name: '14 days' }))
    expect(await screen.findByText(/^14 days: /)).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('reloads fresh numbers after Fetch and Push, never after a share edit', async () => {
    const dirty = view([forced, flow({ dirty: true, pending_count: 1, rows: [row(3749, 50, { change: 'share' }), row(3717, 50)] })])
    const api = routes({
      'POST /api/flows/1001/ops': { body: dirty },
      'POST /api/flows/1001/push': { body: view() },
      'POST /api/campaigns/216250/fetch': { body: view() },
    })
    const user = userEvent.setup()
    renderEditor()
    await screen.findByText(/^7 days: /)
    await user.click(within(rowOf(3749)).getByRole('button', { name: /Pin share/ }))
    await screen.findByRole('button', { name: 'Push to KT' })
    expect(statsCalls(api)).toEqual(['7/false'])
    await user.click(screen.getByRole('button', { name: 'Push to KT' }))
    await waitFor(() => expect(statsCalls(api)).toEqual(['7/false', '7/true']))
    await user.click(await screen.findByRole('button', { name: 'Fetch from KT' }))
    await waitFor(() => expect(statsCalls(api)).toEqual(['7/false', '7/true', '7/true']))
  })

  it('drops a late reply for a period that is no longer shown', async () => {
    let releaseFourteen: () => void = () => {}
    const held = new Promise<void>((resolve) => { releaseFourteen = resolve })
    routes({
      [STATS]: async ({ query }: Call) => {
        const period = query.get('period')!
        if (period === '14') await held
        return { body: ok(period, period === '14' ? 1400 : 100) }
      },
    })
    const user = userEvent.setup()
    renderEditor()
    await screen.findByText(/^7 days: 200 clicks/)
    await user.click(screen.getByRole('button', { name: '14 days' }))
    await user.click(screen.getByRole('button', { name: '30 days' }))
    await screen.findByText(/^30 days: 200 clicks/)
    releaseFourteen()
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.getByText(/^30 days: 200 clicks/)).toBeInTheDocument()
    expect(screen.queryByText(/^14 days:/)).not.toBeInTheDocument()
  })

  it('shows a banner when stats fail, keeps editing, and retries fresh on Try again', async () => {
    let fail = true
    const api = routes({
      [STATS]: () => (fail ? { body: { status: 'unavailable', reason: 'this API key may not read reports' } } : { body: ok() }),
    })
    const user = userEvent.setup()
    renderEditor()
    expect(await screen.findByText(/This API key may not read reports\. Editing and pushing still work\./)).toBeInTheDocument()
    expect(within(rowOf(3749)).getByLabelText('Stats unavailable')).toBeInTheDocument()
    expect(within(rowOf(3749)).getByRole('button', { name: /Pin share/ })).toBeEnabled()
    fail = false
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await within(rowOf(3749)).findByText('EPC $0.50')).toBeInTheDocument()
    expect(statsCalls(api)).toEqual(['7/false', '7/true'])
  })

  it('treats a failed request like an unavailable report', async () => {
    routes({ [STATS]: { status: 500, body: { detail: 'boom' } } })
    renderEditor()
    expect(await screen.findByText(/The stats request failed\./)).toBeInTheDocument()
  })
})
