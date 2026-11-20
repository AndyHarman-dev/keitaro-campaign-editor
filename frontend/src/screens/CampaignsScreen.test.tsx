import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockApi } from '../test/mockApi'
import CampaignsScreen from './CampaignsScreen'

const campaigns = [
  { id: 216250, name: 'RO beauty — spring', alias: 'a', state: 'active', group: 'Team', domain: 'track.example' },
  { id: 216249, name: 'PE joints', alias: 'b', state: 'active', group: null, domain: null },
]
const lookups = {
  domains: [{ id: 1, name: 'track.example' }, { id: 4, name: 'other.example' }],
  groups: [{ id: 2, name: 'Team' }],
  sources: [{ id: 3, name: 'Source' }],
  defaults: { domain_id: 1, group_id: 2, source_id: 3 },
  problems: [],
}
const offers = [{ id: 18813, name: 'Flexacil PE' }, { id: 3717, name: 'Oxys BE' }]

function routes(extra = {}) {
  return mockApi({
    'GET /api/keitaro/ping': { body: { configured: true, reachable: true, status_code: 200, campaigns: 2 } },
    'GET /api/campaigns': ({ query }) => ({
      body: campaigns.filter((c) => !query.get('q') || c.name.toLowerCase().includes(query.get('q')!.toLowerCase())),
    }),
    'GET /api/lookups': { body: lookups },
    'GET /api/offers': ({ query }) => ({
      body: offers.filter((o) => !query.get('q') || o.name.toLowerCase().includes(query.get('q')!.toLowerCase())),
    }),
    ...extra,
  })
}

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<CampaignsScreen />} />
        <Route path="/campaigns/:id" element={<p>Editor page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Name'), 'Spring promo')
  await user.type(screen.getByLabelText('GEO sent to google.com'), 'au{Enter}nz{Enter}')
  await user.type(screen.getByLabelText('Offer'), 'flex')
  await user.click(await screen.findByRole('option', { name: /Flexacil PE/ }))
}

beforeEach(() => {
  vi.spyOn(crypto, 'randomUUID').mockReturnValue('11111111-2222-4333-8444-555555555555')
})
afterEach(() => vi.unstubAllGlobals())

describe('campaign list', () => {
  it('lists campaigns with group and domain, each linking to its editor', async () => {
    routes()
    renderScreen()
    const link = await screen.findByRole('link', { name: /RO beauty — spring/ })
    expect(link).toHaveAttribute('href', '/campaigns/216250')
    expect(within(link).getByText('Team')).toBeInTheDocument()
    expect(within(link).getByText('track.example')).toBeInTheDocument()
    expect(screen.getByText('Keitaro connected')).toBeInTheDocument()
  })

  it('searches on the server', async () => {
    const api = routes()
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('PE joints')
    await user.type(screen.getByLabelText('Search campaigns'), 'spring')
    await waitFor(() => expect(screen.queryByText('PE joints')).not.toBeInTheDocument())
    expect(api.of('GET /api/campaigns').at(-1)!.query.get('q')).toBe('spring')
  })

  it('says when nothing matches', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('PE joints')
    await user.type(screen.getByLabelText('Search campaigns'), 'zzz')
    expect(await screen.findByText('No campaigns match “zzz”.')).toBeInTheDocument()
  })

  it('shows a Keitaro failure instead of the list', async () => {
    routes({
      'GET /api/campaigns': { status: 502, body: { detail: { message: 'Unauthorized', keitaro_status: 401, archived_campaign: false } } },
      'GET /api/keitaro/ping': { body: { configured: true, reachable: false, status_code: 401, campaigns: null } },
    })
    renderScreen()
    expect(await screen.findByText('Unauthorized')).toBeInTheDocument()
    expect(screen.getByText('Keitaro unreachable')).toBeInTheDocument()
  })

  it('reloads the list on refresh', async () => {
    const api = routes()
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('PE joints')
    await user.click(screen.getByRole('button', { name: 'Refresh from Keitaro' }))
    await waitFor(() => expect(api.of('GET /api/campaigns')).toHaveLength(2))
  })
})

describe('new campaign form', () => {
  it('adds GEOs as uppercase chips and removes them', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    await user.type(screen.getByLabelText('GEO sent to google.com'), 'au{Enter}nz{Enter}')
    expect(screen.getByRole('button', { name: 'Remove AU' }).parentElement).toHaveTextContent('AU')
    await user.click(screen.getByRole('button', { name: 'Remove AU' }))
    expect(screen.queryByRole('button', { name: 'Remove AU' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove NZ' })).toBeInTheDocument()
  })

  it('refuses a GEO that is not a 2-letter code and keeps it for editing', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    const geo = screen.getByLabelText('GEO sent to google.com')
    await user.type(geo, 'AUS{Enter}')
    expect(screen.getByText('Use 2-letter ISO codes, e.g. AU.')).toBeInTheDocument()
    expect(geo).toHaveAttribute('aria-invalid', 'true')
    expect(geo).toHaveValue('AUS')
    await user.clear(geo)
    await user.type(geo, 'au{Enter}')
    expect(screen.queryByText('Use 2-letter ISO codes, e.g. AU.')).not.toBeInTheDocument()
  })

  it('previews the two flows it will create', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    const preview = screen.getByRole('region', { name: 'Will create' })
    expect(within(preview).getByText('AU, NZ')).toBeInTheDocument()
    expect(within(preview).getByText('[18813] Flexacil PE')).toBeInTheDocument()
  })

  it('keeps Create disabled until name, GEO and offer are set', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    const create = screen.getByRole('button', { name: 'Create in Keitaro' })
    expect(create).toBeDisabled()
    await fillForm(user)
    expect(create).toBeEnabled()
  })

  it('creates with the defaults and the idempotency key, then opens the editor', async () => {
    const api = routes({ 'POST /api/campaigns': { status: 201, body: { campaign_id: 777 } } })
    const user = userEvent.setup()
    renderScreen()
    await screen.findByRole('option', { name: 'track.example (default)' })
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    expect(await screen.findByText('Editor page')).toBeInTheDocument()
    expect(api.of('POST /api/campaigns')[0].body).toEqual({
      name: 'Spring promo', geos: ['AU', 'NZ'], offer_id: 18813,
      domain_id: 1, group_id: 2, source_id: 3,
      idempotency_key: '11111111-2222-4333-8444-555555555555',
    })
  })

  it('sends an Advanced override', async () => {
    const api = routes({ 'POST /api/campaigns': { status: 201, body: { campaign_id: 777 } } })
    const user = userEvent.setup()
    renderScreen()
    await screen.findByRole('option', { name: 'track.example (default)' })
    await user.click(screen.getByText('Advanced · domain, group, source'))
    await user.selectOptions(screen.getByLabelText('Domain'), '4')
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    await screen.findByText('Editor page')
    expect((api.of('POST /api/campaigns')[0].body as { domain_id: number }).domain_id).toBe(4)
  })

  it('disables Create while the request is running', async () => {
    let release!: () => void
    const gate = new Promise<void>((r) => (release = r))
    routes({ 'POST /api/campaigns': { status: 201, body: { campaign_id: 777 } } })
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: Request) => {
      if (input.method === 'POST') await gate
      return realFetch(input)
    })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled()
    release()
    expect(await screen.findByText('Editor page')).toBeInTheDocument()
  })

  it('shows Keitaro’s error and whether a half-made campaign was archived', async () => {
    routes({
      'POST /api/campaigns': {
        status: 502,
        body: { detail: { message: 'Invalid filter', keitaro_status: 400, archived_campaign: true, campaign_id: 1000 } },
      },
    })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Keitaro rejected the campaign.')
    expect(alert).toHaveTextContent('Invalid filter')
    expect(alert).toHaveTextContent('The flows failed after the campaign was created, so it was archived. You can retry.')
    expect(screen.getByRole('button', { name: 'Create in Keitaro' })).toBeEnabled()
  })

  it('says nothing was created when the campaign itself was refused', async () => {
    routes({
      'POST /api/campaigns': {
        status: 502,
        body: { detail: { message: 'Alias is taken', keitaro_status: 400, archived_campaign: false } },
      },
    })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was created.')
  })

  it('warns when a half-made campaign could not be archived', async () => {
    routes({
      'POST /api/campaigns': {
        status: 502,
        body: { detail: { message: 'Invalid filter', keitaro_status: 400, archived_campaign: false, campaign_id: 1000 } },
      },
    })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Campaign #1000 was created without its flows and could not be archived. Archive it in Keitaro before you retry.')
    expect(alert).not.toHaveTextContent('Nothing was created.')
  })

  it('forgets the picked offer when the offer text is edited', async () => {
    routes()
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    const create = screen.getByRole('button', { name: 'Create in Keitaro' })
    expect(create).toBeEnabled()
    await user.clear(screen.getByLabelText('Offer'))
    await user.type(screen.getByLabelText('Offer'), 'oxys')
    expect(create).toBeDisabled()
  })

  it('lists .env default problems above Advanced', async () => {
    routes({ 'GET /api/lookups': { body: { ...lookups, defaults: { ...lookups.defaults, group_id: null }, problems: ['KEITARO_DEFAULT_GROUP is not set.'] } } })
    renderScreen()
    expect(await screen.findByText('KEITARO_DEFAULT_GROUP is not set.')).toBeInTheDocument()
  })
})

describe('new campaign form errors that are not Keitaro’s', () => {
  it('shows a server message such as a missing default', async () => {
    routes({ 'POST /api/campaigns': { status: 400, body: { detail: 'Choose a group under Advanced: KEITARO_DEFAULT_GROUP is not set.' } } })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not create the campaign.')
    expect(alert).toHaveTextContent('Choose a group under Advanced')
  })

  it('shows a network failure', async () => {
    routes()
    const realFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: Request) => {
      if (input.method === 'POST') throw new TypeError('Failed to fetch')
      return realFetch(input)
    })
    const user = userEvent.setup()
    renderScreen()
    await fillForm(user)
    await user.click(screen.getByRole('button', { name: 'Create in Keitaro' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch')
  })
})
