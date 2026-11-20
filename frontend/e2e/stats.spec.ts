import { expect, test, type Page } from '@playwright/test'
import { flow, row, share } from './helpers'

// Runs against the server started with `python -m app --stats-beta` (see playwright.config.ts).
// One serial story on the seeded demo campaign: later steps change its shares and traffic.
test.describe.configure({ mode: 'serial' })

async function openDemo(page: Page): Promise<number> {
  await page.goto('/')
  await page.getByRole('link', { name: /Demo campaign/ }).click()
  await expect(flow(page)).toBeVisible()
  return Number(page.url().split('/').pop())
}

test('the seeded demo shows a real rise and a drop the band declines to flag', async ({ page }) => {
  await openDemo(page)
  await expect(page.getByRole('group', { name: 'Stats period' })).toBeVisible()
  await expect(row(page, 3749).getByText(/▲ \+\d+%$/)).toBeVisible()
  await expect(row(page, 3717).getByText('within noise')).toBeVisible()
  await expect(row(page, 3717).getByText(/conv\. \(−\d+%, band ±\d+%\)/)).toBeVisible()
  await expect(row(page, 3749).getByText(/^EPC \$\d+\.\d\d$/)).toBeVisible()
  await expect(flow(page).getByText(/^7 days: [\d,]+ clicks · CR/)).toBeVisible()
})

test('switching the period changes the numbers', async ({ page }) => {
  await openDemo(page)
  const week = await flow(page).getByText(/^7 days: /).textContent()
  await page.getByRole('button', { name: 'Today' }).click()
  await expect(flow(page).getByText(/^Today: /)).toBeVisible()
  await expect(row(page, 3749).getByText(/today: mostly pending/)).toBeVisible()
  await page.getByRole('button', { name: '30 days' }).click()
  await expect(flow(page).getByText(/^30 days: /)).not.toHaveText(week!.replace('7 days', '30 days'))
  await page.getByRole('button', { name: '7 days' }).click()
})

test('after a push and a week of traffic, the observed split follows the new shares', async ({ page }) => {
  const campaignId = await openDemo(page)
  await share(page, 3749).click()
  await page.getByLabel('Share for offer 3749').fill('60')
  await page.getByRole('heading', { name: /Flow 2/ }).click()
  await expect(share(page, 3717)).toHaveText('20%')
  await flow(page).getByRole('button', { name: 'Push to KT' }).click()
  await expect(page.getByRole('button', { name: 'Fetch from KT' })).toBeVisible()
  const traffic = await page.request.post('/api/_fake/traffic', {
    data: { campaign_id: campaignId, days: 7, clicks_per_day: 1000, lag: false },
  })
  expect(traffic.status()).toBe(204)
  await page.getByRole('button', { name: 'Fetch from KT' }).click()
  await expect(row(page, 3749).getByText("60% of this flow's clicks went here")).toBeVisible()
  await expect(row(page, 3717).getByText("20% of this flow's clicks went here")).toBeVisible()
})

test('a failed report shows the banner and editing still works', async ({ page }) => {
  await openDemo(page)
  expect((await page.request.post('/api/_fake/fail-next', { data: { status: 503 } })).status()).toBe(204)
  await page.getByRole('button', { name: 'Refresh stats' }).click()
  await expect(page.getByText(/Stats unavailable\./)).toBeVisible()
  await expect(page.getByText(/Keitaro didn't answer in time/)).toBeVisible()
  await share(page, 3717).click()
  await page.getByLabel('Share for offer 3717').fill('30')
  await page.getByRole('heading', { name: /Flow 2/ }).click()
  await expect(share(page, 3717)).toHaveText('30%')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText(/Stats unavailable\./)).toHaveCount(0)
  await expect(row(page, 3749).getByText(/^EPC /)).toBeVisible()
})
