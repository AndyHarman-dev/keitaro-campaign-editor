import { execFileSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { expect, test, type Page } from '@playwright/test'

const NAME = `kce-ui-check-${randomBytes(3).toString('hex')}`
let campaignId: number | null = null

const flow = (page: Page) => page.getByRole('region', { name: 'Flow 2', exact: true })
const row = (page: Page, id: number) => flow(page).getByRole('row', { name: new RegExp(`\\[${id}\\]`) })
const share = (page: Page, id: number) => row(page, id).getByRole('button', { name: /Edit share/ })
const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/live/screens/${name}.png`, fullPage: true })

/** Archives ONLY the campaign this spec created (Keitaro DELETE = archive; never clean_archive). */
test.afterAll(() => {
  if (campaignId === null) return
  execFileSync('uv', ['run', 'python', '-c', `
import asyncio
from app.config import get_settings
from app.keitaro.client import KeitaroClient
async def main():
    s = get_settings()
    kt = KeitaroClient(s.keitaro_base_url, s.keitaro_api_key.get_secret_value())
    c = await kt.get_campaign(${campaignId})
    assert c.name == "${NAME}", "refusing to archive a campaign this run did not create"
    await kt.archive_campaign(c.id)
    await kt.aclose()
asyncio.run(main())
`], { cwd: '../backend', stdio: 'inherit' })
})

test('create, edit, push and re-fetch a throwaway campaign on the real tracker', async ({ page }) => {
  const offers: { id: number; name: string }[] = await (await page.request.get('/api/offers')).json()
  expect(offers.length).toBeGreaterThanOrEqual(1)
  const [first, second] = offers

  await page.goto('/')
  await expect(page.getByText('Keitaro connected')).toBeVisible()
  await expect(page.getByText(/is not set|not found/)).toHaveCount(0)
  await page.getByLabel('Name').fill(NAME)
  await page.getByLabel('GEO sent to google.com').fill('au')
  await page.keyboard.press('Enter')
  await page.getByLabel('Offer').fill(String(first.id))
  await page.getByRole('option').filter({ hasText: first.name }).first().click()
  await shot(page, '1-create-form')
  await page.getByRole('button', { name: 'Create in Keitaro' }).click()
  await expect(page).toHaveURL(/\/campaigns\/\d+$/, { timeout: 30_000 })
  campaignId = Number(page.url().split('/').pop())

  await expect(page.getByRole('heading', { name: NAME })).toBeVisible()
  await expect(share(page, first.id)).toHaveText('100%')
  await expect(page.getByRole('region', { name: 'Flows without offers' })).toContainText('country in AU → https://google.com')

  // A real write that works with a single visible offer: pin, push, fetch.
  await row(page, first.id).getByRole('button', { name: `Pin share of offer ${first.id}` }).click()
  await expect(row(page, first.id)).toContainText('will be pinned')
  await flow(page).getByRole('button', { name: 'Push to KT' }).click()
  await expect(page.getByRole('button', { name: 'Fetch from KT' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: 'Fetch from KT' }).click()
  await expect(share(page, first.id)).toHaveText('100%')
  await expect(row(page, first.id).getByRole('button', { name: `Unpin share of offer ${first.id}` })).toBeVisible()
  await shot(page, '2-after-pin-push-fetch')
  await row(page, first.id).getByRole('button', { name: `Unpin share of offer ${first.id}` }).click()
  await flow(page).getByRole('button', { name: 'Push to KT' }).click()
  await expect(page.getByRole('button', { name: 'Fetch from KT' })).toBeVisible({ timeout: 30_000 })

  if (!second) {
    test.info().annotations.push({ type: 'note', description: 'The API key sees one offer; multi-offer edits skipped.' })
    return
  }
  await flow(page).getByLabel('Add offer to Flow 2').fill(String(second.id))
  await flow(page).getByRole('option').filter({ hasText: second.name }).first().click()
  await flow(page).getByRole('button', { name: 'Add', exact: true }).click()
  await expect(share(page, second.id)).toHaveText('50%')
  await share(page, second.id).click()
  await page.getByLabel(`Share for offer ${second.id}`).fill('70')
  await flow(page).getByRole('button', { name: 'Push to KT' }).click()
  await expect(page.getByRole('button', { name: 'Fetch from KT' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('alert')).toHaveCount(0)

  await page.getByRole('button', { name: 'Fetch from KT' }).click()
  await expect(share(page, first.id)).toHaveText('30%')
  await expect(share(page, second.id)).toHaveText('70%')
  await shot(page, '3-after-push-and-fetch')

  await row(page, second.id).getByRole('button', { name: 'Remove' }).click()
  await expect(share(page, first.id)).toHaveText('100%')
  await flow(page).getByRole('button', { name: 'Push to KT' }).click()
  await expect(page.getByRole('button', { name: 'Fetch from KT' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Fetch from KT' }).click()
  await expect(share(page, first.id)).toHaveText('100%')
  await expect(row(page, second.id).getByRole('button', { name: 'Bring back' })).toBeVisible()
  await shot(page, '4-after-remove-push-fetch')
})
