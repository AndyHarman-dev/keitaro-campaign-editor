import { defineConfig, devices } from '@playwright/test'

// The built app, served by FastAPI against the in-process fake tracker (KEITARO_FAKE=1),
// with a fresh SQLite file per run. Nothing here talks to a real Keitaro.
const PORT = 8765
const DB = '../data/e2e.db'
const env = `KEITARO_FAKE=1 DATABASE_URL=sqlite:///${DB}`

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  reporter: 'list',
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `cd ../backend && mkdir -p ../data && rm -f ${DB} && ${env} uv run alembic upgrade head && ${env} uv run uvicorn app.main:app --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
