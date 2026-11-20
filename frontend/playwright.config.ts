import { defineConfig, devices } from '@playwright/test'

// The built app, served by FastAPI against the in-process fake tracker (KEITARO_FAKE=1),
// with a fresh SQLite file per run. Nothing here talks to a real Keitaro.
//
// Two servers, because stats & trends are a beta switched at start-up: 8765 runs with the
// beta off (every existing spec, plus the placeholders check), 8766 runs through the launcher
// with --stats-beta. Each has its own database file: Playwright starts the servers one after
// another, and a shared file would be deleted under the first one.
const server = (port: number, db: string, start: string) => {
  const env = `KEITARO_FAKE=1 DATABASE_URL=sqlite:///../data/${db}`
  return {
    command: `cd ../backend && mkdir -p ../data && rm -f ../data/${db} && ${env} uv run alembic upgrade head && ${env} ${start} --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  }
}

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  reporter: 'list',
  use: { trace: 'retain-on-failure' },
  projects: [
    { name: 'beta-off', testIgnore: /stats\.spec\.ts/, use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:8765' } },
    { name: 'stats-beta', testMatch: /stats\.spec\.ts/, use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:8766' } },
  ],
  webServer: [
    server(8765, 'e2e.db', 'uv run uvicorn app.main:app'),
    server(8766, 'e2e-beta.db', 'uv run python -m app --stats-beta'),
  ],
})
