import { defineConfig, devices } from '@playwright/test'

// End-to-end tests against the real server and built frontend, with a throwaway database.
// Run: npm run build && npx playwright test   (CI does this; see .github/workflows/ci.yml)
export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:8010', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: 'cd .. && python -m uvicorn airaware.server.app:app --port 8010',
    url: 'http://127.0.0.1:8010/api/health',
    timeout: 180_000,
    reuseExistingServer: false,
    env: { AIRAWARE_DB: '/tmp/airaware-e2e.db', AIRAWARE_REFRESH: '0' },
  },
})
