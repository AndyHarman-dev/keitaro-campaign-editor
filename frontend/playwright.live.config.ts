import { defineConfig, devices } from '@playwright/test'

// OPT-IN: drives the built app against the REAL tracker from ../.env (`npm run e2e:live`).
// It creates one throwaway campaign (kce-ui-check-…), edits only that campaign, and
// archives it at the end. Never part of `npm run e2e`.
const PORT = 8767
const DB = '../data/e2e-live.db'
const env = `DATABASE_URL=sqlite:///${DB}`

export default defineConfig({
  testDir: './e2e-live',
  workers: 1,
  timeout: 120_000,
  reporter: 'list',
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'on', video: 'on', screenshot: 'on' },
  outputDir: 'test-results/live',
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `cd ../backend && mkdir -p ../data && rm -f ${DB} && ${env} uv run alembic upgrade head && ${env} uv run uvicorn app.main:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
