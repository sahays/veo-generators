/**
 * Playwright fixtures for tests that run the app against the stub API.
 *
 *   import { expect, test } from './fixtures.ts'
 *
 * Every test starts authenticated (the persisted auth store is seeded before any
 * page script runs) and with the stub restored to its seed state.
 */
import path from 'node:path'
import { test as base, expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import type { EngagementRecord, SceneAnalysisRecord } from '../../src/types/insights.ts'
import { stubOrigin } from './ports.ts'

/** zustand-persist payload of `useAuthStore` (localStorage key `veo-auth`). */
const AUTH_STORAGE_KEY = 'veo-auth'
const AUTH_STATE = {
  state: { inviteCode: 'stub-master', isMaster: true, isPower: true, isAuthenticated: true },
  version: 0,
}

/** Next.js dev error overlay (rendered inside `<nextjs-portal>`; Playwright pierces its shadow root). */
const CRASH_OVERLAY = '[data-nextjs-dialog], [data-nextjs-error-overlay]'

export interface StubControl {
  /** Origin of the stub API, e.g. `http://127.0.0.1:8787`. */
  origin: string
  /** Restores the seed records. Runs automatically before every test. */
  reset: () => Promise<void>
  /** Moves a scene analysis job forward without polling; returns the record after the move. */
  advanceSceneAnalysis: (id: string, steps?: number) => Promise<SceneAnalysisRecord>
  /**
   * Moves an engagement job forward without polling; returns the record after the move.
   * A job waiting on its scene analysis stays waiting until that analysis is completed
   * (`advanceSceneAnalysis`); this never advances the analysis itself.
   */
  advanceEngagement: (id: string, steps?: number) => Promise<EngagementRecord>
}

export interface StubFixtures {
  stub: StubControl
  /** Uncaught exceptions thrown in the page so far. */
  pageErrors: string[]
  /** `console.error` output so far (React warnings included). Reported after the test, never fatal. */
  consoleErrors: string[]
  /** Saves a screenshot of the whole page, including what `<main>` would scroll to, to `e2e/stub/screenshots/<name>.png`. */
  shot: (name: string) => Promise<void>
  /** Fails when the page threw an uncaught exception or shows the dev error overlay. */
  expectNoCrash: () => Promise<void>
}

/** Tallest screenshot `shot` will take, in CSS pixels. */
const MAX_SHOT_HEIGHT = 4000

function stubControl(request: APIRequestContext): StubControl {
  const origin = stubOrigin()
  return {
    origin,
    reset: async () => {
      const res = await request.post(`${origin}/__stub/reset`)
      expect(res.ok(), 'stub reset failed: is the stub server running?').toBe(true)
    },
    advanceSceneAnalysis: async (id, steps = 1) => {
      const res = await request.post(
        `${origin}/__stub/scene-analysis/${encodeURIComponent(id)}/advance`,
        { data: { steps } },
      )
      expect(res.ok(), `stub advance failed for ${id}`).toBe(true)
      return (await res.json()) as SceneAnalysisRecord
    },
    advanceEngagement: async (id, steps = 1) => {
      const res = await request.post(
        `${origin}/__stub/engagement/${encodeURIComponent(id)}/advance`,
        { data: { steps } },
      )
      expect(res.ok(), `stub advance failed for ${id}`).toBe(true)
      return (await res.json()) as EngagementRecord
    },
  }
}

function seedAuth(entry: { key: string; value: string }): void {
  try {
    window.localStorage.setItem(entry.key, entry.value)
  } catch {
    // about:blank and other opaque origins have no storage.
  }
}

function collectPageErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(err.message))
  return errors
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })
  return errors
}

/** Attaches the console errors to the report and prints a one-line summary under the test. */
async function reportConsoleErrors(errors: readonly string[], testInfo: TestInfo): Promise<void> {
  if (errors.length === 0) return
  await testInfo.attach('console-errors.txt', { body: errors.join('\n\n'), contentType: 'text/plain' })
  const first = errors[0].replace(/\s+/g, ' ').slice(0, 160)
  process.stdout.write(`    [stub-e2e] ${errors.length} console error(s) in "${testInfo.title}": ${first}\n`)
}

export const test = base.extend<StubFixtures>({
  context: async ({ context }, use) => {
    await context.addInitScript(seedAuth, { key: AUTH_STORAGE_KEY, value: JSON.stringify(AUTH_STATE) })
    await use(context)
  },
  stub: [
    async ({ request }, use) => {
      const control = stubControl(request)
      await control.reset()
      await use(control)
    },
    { auto: true },
  ],
  pageErrors: [
    async ({ page }, use) => {
      await use(collectPageErrors(page))
    },
    { auto: true },
  ],
  consoleErrors: [
    async ({ page }, use, testInfo) => {
      const errors = collectConsoleErrors(page)
      await use(errors)
      await reportConsoleErrors(errors, testInfo)
    },
    { auto: true },
  ],
  shot: async ({ page }, use, testInfo) => {
    const dir = path.join(testInfo.project.testDir, 'screenshots')
    await use(async (name) => {
      // The app scrolls inside <main>, not the window, so "full page" means growing the
      // viewport until <main> no longer needs to scroll, then restoring it.
      const original = page.viewportSize()
      const needed = await page.evaluate(() => {
        const main = document.querySelector('main')
        return main ? Math.ceil(main.scrollHeight - main.clientHeight) : 0
      })
      if (original && needed > 0) {
        await page.setViewportSize({ width: original.width, height: Math.min(original.height + needed, MAX_SHOT_HEIGHT) })
      }
      await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true })
      if (original && needed > 0) await page.setViewportSize(original)
    })
  },
  expectNoCrash: async ({ page, pageErrors }, use) => {
    await use(async () => {
      await expect(page.locator(CRASH_OVERLAY), 'Next.js error overlay is showing').toHaveCount(0)
      expect(pageErrors, 'uncaught exceptions in the page').toEqual([])
    })
  },
})

export { expect }
