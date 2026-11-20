import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flow, forced, row, view } from '../test/editorFixture'
import { mockApi, type Call } from '../test/mockApi'
import EditorScreen from './EditorScreen'

const offers = [{ id: 3749, name: 'Offer 3749' }, { id: 3717, name: 'Offer 3717' }, { id: 11111, name: 'Offer 11111' },
  { id: 4242, name: 'Fresh offer' }]

function routes(extra = {}) {
  return mockApi({
    'GET /api/campaigns/216250/editor': { body: view() },
    'GET /api/offers': ({ query }) => ({
      body: offers.filter((o) => !query.get('q') || o.name.toLowerCase().includes(query.get('q')!.toLowerCase())),
    }),
    ...extra,
  })
}

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={['/campaigns/216250']}>
      <Routes>
        <Route path="/campaigns/:id" element={<EditorScreen />} />
        <Route path="/" element={<p>Campaigns page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

const flowSection = () => screen.getByRole('region', { name: 'Flow 2' })
const rowOf = (id: number) => screen.getByRole('row', { name: new RegExp(`\\[${id}\\]`) })

afterEach(() => vi.unstubAllGlobals())

describe('editor layout', () => {
  it('shows each flow with offers as a table and the others below it', async () => {
    routes({
      'GET /api/campaigns/216250/editor': {
        body: view([forced, flow({ rows: [row(3749, 50, { preview_url: 'https://tracker.example/p.png' }), row(500, 50, { name: null })] })]),
      },
    })
    renderEditor()
    expect(await screen.findByRole('heading', { name: 'RO beauty — spring' })).toBeInTheDocument()
    const section = flowSection()
    expect(within(section).getByRole('heading', { name: 'Flow 2 #1001' })).toBeInTheDocument()
    expect(within(section).getByText(/regular · position 2 · total/)).toHaveTextContent('total 100%')
    expect(within(rowOf(3749)).getByRole('link', { name: 'preview' })).toHaveAttribute('href', 'https://tracker.example/p.png')
    expect(within(rowOf(500)).queryByRole('link', { name: 'preview' })).not.toBeInTheDocument()
    expect(within(rowOf(500)).getByText('no access to this offer')).toBeInTheDocument()
    const others = screen.getByRole('region', { name: 'Flows without offers' })
    expect(others).toHaveTextContent('Flow 1 #1000 · forced · country in AU → https://google.com')
    expect(screen.getByRole('link', { name: 'View in KT' })).toHaveAttribute('href', 'https://tracker.example/admin/#!/campaigns/216250')
  })

  it('links back to the campaign list', async () => {
    routes()
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('link', { name: '← Campaigns' }))
    expect(screen.getByText('Campaigns page')).toBeInTheDocument()
  })

  it('shows a Keitaro failure when the campaign cannot be opened', async () => {
    routes({ 'GET /api/campaigns/216250/editor': { status: 502, body: { detail: { message: 'Not found', keitaro_status: 404, archived_campaign: false } } } })
    renderEditor()
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
  })
})

describe('row states', () => {
  it('tags pending and Keitaro-side changes', async () => {
    routes({
      'GET /api/campaigns/216250/editor': {
        body: view([flow({
          rows: [
            row(1, 50, { change: 'share', base_share: 34 }),
            row(2, 50, { change: 'added', base_share: null }),
            row(3, 0, { status: 'removed', removed_by: 'local', change: 'removed', base_share: 33 }),
            row(4, 0, { status: 'removed', removed_by: 'keitaro' }),
            row(5, 0, { status: 'removed', removed_by: 'keitaro', change: null, archived: true }),
            row(6, 0, { change: 'pin', pinned: true, base_share: 0 }),
            row(7, 0, { change: 'pin', pinned: false, base_share: 0 }),
          ],
        })]),
      },
    })
    renderEditor()
    expect(within(await screen.findByRole('row', { name: /\[1\]/ })).getByText('was 34%')).toBeInTheDocument()
    expect(within(rowOf(2)).getByText('new')).toBeInTheDocument()
    expect(within(rowOf(3)).getByText('will be removed')).toBeInTheDocument()
    expect(within(rowOf(3)).getByRole('button', { name: 'Bring back' })).toBeInTheDocument()
    expect(within(rowOf(4)).getByText('removed in Keitaro')).toBeInTheDocument()
    expect(within(rowOf(5)).getByText('archived in Keitaro · can’t be restored')).toBeInTheDocument()
    expect(within(rowOf(5)).queryByRole('button', { name: 'Bring back' })).not.toBeInTheDocument()
    expect(within(rowOf(5)).getByRole('button', { name: 'Remove' })).toBeInTheDocument()
    expect(within(rowOf(6)).getByText('will be pinned')).toBeInTheDocument()
    expect(within(rowOf(7)).getByText('will be unpinned')).toBeInTheDocument()
  })

  it('marks a brought-back row as will be restored', async () => {
    routes({ 'GET /api/campaigns/216250/editor': { body: view([flow({ rows: [row(4, 100, { change: 'restored', base_share: 0 })] })]) } })
    renderEditor()
    expect(within(await screen.findByRole('row', { name: /\[4\]/ })).getByText('will be restored')).toBeInTheDocument()
  })
})

describe('staged operations', () => {
  it('sends Remove with the flow version and shows the returned state', async () => {
    const dirty = view([forced, flow({ dirty: true, pending_count: 3, version: 4, rows: [
      row(3749, 0, { status: 'removed', removed_by: 'local', change: 'removed', base_share: 34 }),
      row(3717, 50, { change: 'share', base_share: 33 }), row(11111, 50, { change: 'share', base_share: 33 })] })])
    const api = routes({ 'POST /api/flows/1001/ops': { body: dirty } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(within(await screen.findByRole('row', { name: /\[3749\]/ })).getByRole('button', { name: 'Remove' }))
    expect(api.of('POST /api/flows/1001/ops')[0].body).toEqual({ version: 3, op: { kind: 'remove', offer_id: 3749 } })
    expect(await within(flowSection()).findByText('3 pending changes')).toBeInTheDocument()
    expect(within(flowSection()).getByRole('button', { name: 'Push to KT' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Push all to KT (1)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Fetch from KT' })).not.toBeInTheDocument()
  })

  it('brings back, pins and edits shares', async () => {
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: view([flow({ rows: [row(3749, 50, { pinned: true }), row(3717, 50), row(9, 0, { status: 'removed', removed_by: 'keitaro' })] })]) },
      'POST /api/flows/1001/ops': ({ body }: Call) => ({ body: view([flow({ version: 3 + (body as { version: number }).version })]) }),
    })
    const user = userEvent.setup()
    renderEditor()
    const pin = within(await screen.findByRole('row', { name: /\[3749\]/ })).getByRole('button', { name: 'Unpin share of offer 3749' })
    expect(pin).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(rowOf(9)).getByRole('button', { name: 'Bring back' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/ops')).toHaveLength(1))
    await user.click(within(rowOf(3749)).getByRole('button', { name: 'Pin share of offer 3749' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/ops')).toHaveLength(2))
    await user.click(within(rowOf(3717)).getByRole('button', { name: /Edit share of offer 3717/ }))
    await user.clear(screen.getByLabelText('Share for offer 3717'))
    await user.type(screen.getByLabelText('Share for offer 3717'), '60{Enter}')
    await waitFor(() => expect(api.of('POST /api/flows/1001/ops')).toHaveLength(3))
    expect(api.of('POST /api/flows/1001/ops').map((c) => (c.body as { op: unknown }).op)).toEqual([
      { kind: 'bring_back', offer_id: 9 },
      { kind: 'toggle_pin', offer_id: 3749 },
      { kind: 'set_share', offer_id: 3717, share: 60 },
    ])
    expect((api.of('POST /api/flows/1001/ops')[1].body as { version: number }).version).toBe(6)
  })

  it('forgets an archived row instead of staging a remove', async () => {
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: view([flow({ rows: [row(1, 100), row(5, 0, { status: 'removed', removed_by: 'keitaro', archived: true })] })]) },
      'POST /api/flows/1001/forget': { body: view([flow({ rows: [row(1, 100)] })]) },
    })
    const user = userEvent.setup()
    renderEditor()
    await user.click(within(await screen.findByRole('row', { name: /\[5\]/ })).getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/forget')[0].body).toEqual({ version: 3, offer_id: 5 }))
    await waitFor(() => expect(screen.queryByRole('row', { name: /\[5\]/ })).not.toBeInTheDocument())
  })

  it('adds an offer picked in the flow’s Add box', async () => {
    const api = routes({ 'POST /api/flows/1001/ops': { body: view() } })
    const user = userEvent.setup()
    renderEditor()
    const add = within(await screen.findByRole('region', { name: 'Flow 2' })).getByRole('button', { name: 'Add' })
    expect(add).toBeDisabled()
    await user.type(screen.getByLabelText('Add offer to Flow 2'), 'fresh')
    await user.click(await screen.findByRole('option', { name: /Fresh offer/ }))
    await user.click(add)
    await waitFor(() => expect(api.of('POST /api/flows/1001/ops')[0].body).toEqual({ version: 3, op: { kind: 'add', offer_id: 4242 } }))
  })

  it('shows notes from the backend and lets them be dismissed', async () => {
    routes({ 'POST /api/flows/1001/ops': { body: view(undefined, { notes: ['Flow 2: Auto-unpinned [3749]: the pinned shares did not fit in 100%.'] }) } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(within(await screen.findByRole('row', { name: /\[3717\]/ })).getByRole('button', { name: 'Remove' }))
    const status = await screen.findByText(/Auto-unpinned \[3749\]/)
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(status).not.toBeInTheDocument()
  })
})

describe('fetch, push and cancel', () => {
  const dirtyView = () => view([forced, flow({ dirty: true, pending_count: 1, rows: [row(3749, 50), row(4242, 50, { change: 'added', base_share: null })] })])

  it('fetches when clean', async () => {
    const api = routes({ 'POST /api/campaigns/216250/fetch': { body: view(undefined, { notes: ['Flow 2: Offer [1] was removed from this flow in Keitaro. Bring back + Push re-attaches it.'] }) } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Fetch from KT' }))
    expect(await screen.findByText(/was removed from this flow in Keitaro/)).toBeInTheDocument()
    expect(api.of('POST /api/campaigns/216250/fetch')).toHaveLength(1)
  })

  it('shows Fetch as busy for a visible moment, even when Keitaro answers at once', async () => {
    routes({ 'POST /api/campaigns/216250/fetch': { body: view(undefined, { notes: ['Fetched.'] }) } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Fetch from KT' }))
    const busy = screen.getByRole('button', { name: 'Fetching…' })
    expect(busy).toBeDisabled()
    expect(busy).toHaveAttribute('aria-busy', 'true')
    expect(await screen.findByText('Fetched.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fetching…' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Fetch from KT' })).toBeEnabled()
  })

  it('pushes and cancels one flow', async () => {
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: dirtyView() },
      'POST /api/flows/1001/push': { body: view() },
      'POST /api/flows/1001/cancel': { body: view() },
    })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await within(await screen.findByRole('region', { name: 'Flow 2' })).findByRole('button', { name: 'Push to KT' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/push')[0].body).toEqual({ version: 3 }))
    expect(await screen.findByRole('button', { name: 'Fetch from KT' })).toBeInTheDocument()
  })

  it('sends a push typed right after a share edit only once the edit is applied, with its version', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    const edited = dirtyView()
    edited.flows[1] = { ...edited.flows[1], version: 4 }
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: dirtyView() },
      'POST /api/flows/1001/ops': { body: edited },
      'POST /api/flows/1001/push': { body: view(undefined) },
    })
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: Request) => {
      if (input.url.endsWith('/ops')) await gate
      return realFetch(input)
    })
    const user = userEvent.setup()
    renderEditor()
    const section = await screen.findByRole('region', { name: 'Flow 2' })
    await user.click(within(section).getAllByRole('button', { name: /Edit share of offer/ })[0])
    await user.type(within(section).getByRole('spinbutton'), '0')
    await user.click(within(section).getByRole('button', { name: 'Push to KT' }))
    expect(api.of('POST /api/flows/1001/push')).toHaveLength(0)
    release()
    await waitFor(() => expect(api.of('POST /api/flows/1001/push')).toHaveLength(1))
    expect(api.of('POST /api/flows/1001/push')[0].body).toEqual({ version: 4 })
    expect(api.calls.map((c) => c.path).filter((p) => p.startsWith('/api/flows'))).toEqual(
      ['/api/flows/1001/ops', '/api/flows/1001/push'])
  })

  it('cancels one flow', async () => {
    const api = routes({ 'GET /api/campaigns/216250/editor': { body: dirtyView() }, 'POST /api/flows/1001/cancel': { body: view() } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await within(await screen.findByRole('region', { name: 'Flow 2' })).findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/cancel')[0].body).toEqual({ version: 3 }))
  })

  it('pushes and cancels everything with the versions it saw', async () => {
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: dirtyView() },
      'POST /api/campaigns/216250/push': { body: dirtyView() },
      'POST /api/campaigns/216250/cancel': { body: view() },
    })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Push all to KT (1)' }))
    await waitFor(() => expect(api.of('POST /api/campaigns/216250/push')[0].body).toEqual({ versions: { 1000: 1, 1001: 3 } }))
    await user.click(screen.getByRole('button', { name: 'Cancel all' }))
    await waitFor(() => expect(api.of('POST /api/campaigns/216250/cancel')).toHaveLength(1))
  })

  it('blocks a push that conflicts with Keitaro and offers Fetch & merge', async () => {
    const api = routes({
      'GET /api/campaigns/216250/editor': { body: dirtyView() },
      'POST /api/flows/1001/push': { status: 409, body: { detail: { kind: 'conflict', message: 'Flow 2 was changed in Keitaro since your last fetch.' } } },
      'POST /api/campaigns/216250/fetch': { body: dirtyView() },
    })
    const user = userEvent.setup()
    renderEditor()
    const section = await screen.findByRole('region', { name: 'Flow 2' })
    await user.click(await within(section).findByRole('button', { name: 'Push to KT' }))
    const alert = await within(section).findByRole('alert')
    expect(alert).toHaveTextContent('Flow 2 was changed in Keitaro since your last fetch.')
    expect(within(section).getByRole('button', { name: 'Push to KT' })).toBeDisabled()
    await user.click(within(alert).getByRole('button', { name: 'Fetch & merge' }))
    expect(within(alert).getByRole('button', { name: 'Fetching…' })).toBeDisabled()
    await waitFor(() => expect(api.of('POST /api/campaigns/216250/fetch')).toHaveLength(1))
    await waitFor(() => expect(within(section).queryByRole('alert')).not.toBeInTheDocument())
    expect(within(section).getByRole('button', { name: 'Push to KT' })).toBeEnabled()
  })

  it('asks for a reload when another tab changed the flow', async () => {
    const api = routes({ 'POST /api/flows/1001/ops': { status: 409, body: { detail: { kind: 'stale', message: 'This flow changed in another tab or window. Reload to see the latest state.' } } } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(within(await screen.findByRole('row', { name: /\[3717\]/ })).getByRole('button', { name: 'Remove' }))
    const alert = await within(flowSection()).findByRole('alert')
    await user.click(within(alert).getByRole('button', { name: 'Reload' }))
    await waitFor(() => expect(api.of('GET /api/campaigns/216250/editor')).toHaveLength(2))
  })

  it('reports other failures at the top', async () => {
    routes({ 'POST /api/flows/1001/ops': { status: 502, body: { detail: { message: 'Keitaro is down', keitaro_status: 0, archived_campaign: false } } } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(within(await screen.findByRole('row', { name: /\[3717\]/ })).getByRole('button', { name: 'Remove' }))
    expect(await screen.findByText('Keitaro is down')).toBeInTheDocument()
  })
})

describe('show all offers', () => {
  it('lists every readable offer, marks those in a flow and adds the rest', async () => {
    const api = routes({ 'POST /api/flows/1001/ops': { body: view() } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Show all offers' }))
    const panel = screen.getByRole('region', { name: /All offers in Keitaro/ })
    const present = await within(panel).findByRole('listitem', { name: /Offer 3749/ })
    expect(within(present).getByText('in Flow 2')).toBeInTheDocument()
    await user.type(within(panel).getByLabelText('Search all offers'), 'fresh')
    await waitFor(() => expect(within(panel).queryByRole('listitem', { name: /Offer 3749/ })).not.toBeInTheDocument())
    await user.click(within(panel).getByRole('button', { name: 'Add to Flow 2' }))
    await waitFor(() => expect(api.of('POST /api/flows/1001/ops')[0].body).toEqual({ version: 3, op: { kind: 'add', offer_id: 4242 } }))
    await user.click(screen.getByRole('button', { name: 'Hide all offers' }))
    expect(screen.queryByRole('region', { name: /All offers in Keitaro/ })).not.toBeInTheDocument()
  })

  it('offers to add back an offer that is only a removed row', async () => {
    routes({ 'GET /api/campaigns/216250/editor': { body: view([flow({ rows: [row(3749, 100), row(3717, 0, { status: 'removed', removed_by: 'keitaro' })] })]) } })
    const user = userEvent.setup()
    renderEditor()
    await user.click(await screen.findByRole('button', { name: 'Show all offers' }))
    const panel = screen.getByRole('region', { name: /All offers in Keitaro/ })
    const removed = await within(panel).findByRole('listitem', { name: /Offer 3717/ })
    expect(within(removed).queryByText('in Flow 2')).not.toBeInTheDocument()
    expect(within(removed).getByRole('button', { name: 'Add to Flow 2' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hide all offers' }))
    expect(screen.queryByRole('region', { name: /All offers in Keitaro/ })).not.toBeInTheDocument()
  })
})

describe('stats beta off (parity gate: the editor looks exactly as before the beta)', () => {
  it('keeps the placeholders, with no period switch and no flow totals', async () => {
    const api = routes()
    renderEditor()
    await screen.findByRole('heading', { name: 'RO beauty — spring' })
    const row = rowOf(3749)
    expect(within(row).getByLabelText('No stats yet')).toHaveTextContent('—')
    expect(within(row).getByLabelText('No trends yet')).toHaveTextContent('—')
    expect(screen.queryByRole('group', { name: 'Stats period' })).not.toBeInTheDocument()
    expect(screen.queryByText(/clicks · CR/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Stats unavailable/)).not.toBeInTheDocument()
    expect(api.calls.filter((c) => !c.path.endsWith('/stats')).map((c) => `${c.method} ${c.path}`))
      .toEqual(['GET /api/campaigns/216250/editor'])
  })
})
