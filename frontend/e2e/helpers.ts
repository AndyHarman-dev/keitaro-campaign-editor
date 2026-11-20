import { randomUUID } from 'node:crypto'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

/** Creates a campaign through the API (the UI path has its own spec) and opens its editor. */
export async function openNewCampaign(page: Page, offerId: number): Promise<number> {
  const created = await page.request.post('/api/campaigns', {
    data: { name: `e2e ${Date.now()}`, geos: ['AU'], offer_id: offerId, idempotency_key: randomUUID() },
  })
  expect(created.status()).toBe(201)
  const { campaign_id } = await created.json()
  await page.goto(`/campaigns/${campaign_id}`)
  await expect(flow(page)).toBeVisible()
  return campaign_id
}

export const flow = (page: Page, name = 'Flow 2') => page.getByRole('region', { name, exact: true })
export const row = (page: Page, offerId: number) => flow(page).getByRole('row', { name: new RegExp(`\\[${offerId}\\]`) })
export const share = (page: Page, offerId: number) => row(page, offerId).getByRole('button', { name: /Edit share/ })

export async function streamId(page: Page): Promise<number> {
  const heading = await flow(page).getByRole('heading').textContent()
  return Number(heading!.split('#')[1])
}

export async function addOffer(page: Page, query: string, optionName: RegExp) {
  await flow(page).getByLabel('Add offer to Flow 2').fill(query)
  await flow(page).getByRole('option', { name: optionName }).click()
  await flow(page).getByRole('button', { name: 'Add', exact: true }).click()
}

/** Simulates someone changing Keitaro directly (fake mode only). */
export async function inKeitaro(request: APIRequestContext, path: string) {
  expect((await request.post(`/api/_fake${path}`)).status()).toBe(204)
}
