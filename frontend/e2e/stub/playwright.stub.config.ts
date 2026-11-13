/**
 * Playwright config for browser tests against the local stub API.
 * Completely separate from `frontend/playwright.config.ts` (which targets a deployed app).
 *
 *   npx playwright test -c e2e/stub/playwright.stub.config.ts      (from frontend/)
 *
 * Starts (or reuses) two local servers: the stub API on 127.0.0.1:8787 and
 * `next dev` on 127.0.0.1:5199 pointed at it. Uses the system Google Chrome;
 * Playwright's own browsers are not needed. Paths below are relative to this file.
 */
import { defineConfig } from '@playwright/test'
import { APP_ORIGIN, APP_PORT, HOST, stubOrigin, stubPort } from './ports.ts'

const STUB_ORIGIN = stubOrigin()
/** Set when Chrome is not where Playwright's `chrome` channel looks for it. */
const CHROME_PATH = process.env.STUB_CHROME_PATH

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.stub.spec.ts',
  outputDir: './test-results',
  // One worker: every test resets and then mutates the same in-memory stub state.
  fullyParallel: false,
  workers: 1,
  // No retries: a failure is a failure. The dev-server 500s once seen here came from Tailwind
  // watching the files Playwright writes under e2e/ and recompiling mid-request; `src/index.css`
  // now excludes e2e/ from its sources (`@source not "../e2e"`), which stopped them.
  retries: 0,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: APP_ORIGIN,
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: CHROME_PATH ? { executablePath: CHROME_PATH } : {},
  },
  webServer: [
    {
      name: 'stub-api',
      command: 'node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON server.ts',
      cwd: '.',
      url: `${STUB_ORIGIN}/__stub/health`,
      env: { STUB_PORT: String(stubPort()) },
      reuseExistingServer: true,
      timeout: 20_000,
    },
    {
      name: 'next-dev',
      command: `npx next dev --hostname ${HOST} --port ${APP_PORT}`,
      cwd: '../..',
      url: APP_ORIGIN,
      // Every upstream the Server Action can pick is pinned to the stub, so no request leaves this machine.
      env: {
        FASTAPI_INTERNAL_ORIGIN: STUB_ORIGIN,
        AGENTS_SERVICE_ORIGIN: STUB_ORIGIN,
        PRODUCTIONS_SERVICE_ORIGIN: STUB_ORIGIN,
        NEXT_TELEMETRY_DISABLED: '1',
      },
      reuseExistingServer: true,
      // The first request compiles the whole app.
      timeout: 240_000,
    },
  ],
})
