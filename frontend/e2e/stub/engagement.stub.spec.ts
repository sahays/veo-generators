/**
 * Engagement landing and create pages against the stub API: the seeded
 * reports, creating a job from a template, `?analysis=` preselection, and
 * creating one from an uploaded BARC file (preview, mapping, offset).
 * Screenshots are written to `e2e/stub/screenshots/`.
 */
import path from 'node:path'
import type { Page } from '@playwright/test'
import type { EngagementRecord } from '../../src/types/insights.ts'
import { AD_SPOT_ID } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { expect, test } from './fixtures.ts'

// Playwright loads spec files as CommonJS, so `__dirname` is available here (and `import.meta` is not).
const FIXTURE_DIR = path.join(__dirname, 'data', 'engagement')
const BARC_CSV = path.join(FIXTURE_DIR, 'barc-kadak-chai-monsoon.csv')
const UNMAPPABLE_CSV = path.join(FIXTURE_DIR, 'unmappable-notes.csv')

const startButton = (page: Page) => page.getByRole('main').getByRole('button', { name: 'Start Analysis' })

async function openCreate(page: Page, query = ''): Promise<void> {
  await page.goto(`/engagement/new${query}`)
  await expect(page.getByRole('radio', { name: /Jumpy/ })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId(`analysis-${AD_SPOT_ID}`)).toBeVisible()
}

async function useLightTheme(page: Page): Promise<void> {
  await page.addInitScript(() => window.localStorage.setItem('theme', 'light'))
}

test('landing lists the seeded reports with status, signal badge, duration and headline', async ({ page, shot, expectNoCrash }) => {
  await page.goto('/engagement')
  const main = page.getByRole('main')
  const card = (title: string) => main.locator('button', { hasText: title }).first()

  const template = card('Monsoon spot — Jumpy template')
  await expect(template).toBeVisible({ timeout: 60_000 })
  await expect(template).toContainText('Completed')
  await expect(template.getByTestId('signal-badge')).toHaveText('Template (simulated) · Jumpy')
  await expect(template).toContainText('0:45')
  await expect(template).toContainText('On this simulated curve the banter with Mr. Rao sits highest')

  const barc = card('Monsoon spot — BARC ratings')
  await expect(barc.getByTestId('signal-badge')).toHaveText('BARC · barc-kadak-chai-monsoon.csv')
  await expect(barc.getByTestId('signal-badge')).toHaveAttribute('data-simulated', 'false')
  await expect(barc).toContainText('Ratings build through the tea ritual')

  // A finished report whose language-model step failed says so instead of showing nothing.
  await expect(card('Monsoon spot — numbers only')).toContainText('No headline was written for this report.')
  // Jobs that are not finished show their state and no headline.
  await expect(card('Monsoon drama trailer — engagement').getByTestId('signal-badge')).toHaveText('Template (simulated) · High engagement')
  await expect(card('Monsoon spot — missing CSV')).toContainText('Failed')
  await expect(card('Monsoon spot — in progress')).toBeVisible()

  await expectNoCrash()
  await shot('engagement-landing')
})

test('landing in the light theme', async ({ page, shot }) => {
  await useLightTheme(page)
  await page.goto('/engagement')
  await expect(page.getByRole('main').getByText('Monsoon spot — BARC ratings', { exact: true })).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await shot('engagement-landing-light')
})

test('create from an analysed video and a template', async ({ page, stub, request, shot, expectNoCrash }) => {
  await openCreate(page)
  const main = page.getByRole('main')

  // Analysed videos is the default tab; the list shows each analysis with its status.
  await expect(main.getByRole('tab', { name: 'Analysed videos' })).toHaveAttribute('aria-selected', 'true')
  await expect(main.getByTestId(`analysis-${AD_SPOT_ID}`)).toContainText('Completed')
  await expect(main.getByTestId(`analysis-${AD_SPOT_ID}`)).toContainText('Analysis is reused')
  await expect(main.getByTestId('analysis-sa-fixture-running')).toContainText('The report starts when it finishes')
  await expect(main.getByTestId('analysis-sa-fixture-failed')).toBeDisabled()

  // One radio per template, each with a sparkline, plus the BARC option.
  await expect(main.getByRole('radio')).toHaveCount(6)
  await expect(main.getByTestId('template-sparkline')).toHaveCount(5)
  await expect(main.getByTestId('signal-option-slow_burn')).toContainText('Engagement builds gradually to a climax')
  await expect(startButton(page)).toBeDisabled()
  await shot('engagement-new')

  await main.getByTestId(`analysis-${AD_SPOT_ID}`).click()
  await expect(startButton(page)).toBeDisabled()
  await main.getByRole('radio', { name: /Slow burn/ }).check()
  await expect(startButton(page)).toBeEnabled()
  await shot('engagement-new-template-chosen')
  await startButton(page).click()

  await expect(page).toHaveURL(/\/engagement\/eng-stub-1$/)
  const created = (await (await request.get(`${stub.origin}/api/v1/engagement/eng-stub-1`)).json()) as EngagementRecord
  expect(created.scene_analysis_id).toBe(AD_SPOT_ID)
  expect(created.signal).toMatchObject({ kind: 'template', template_id: 'slow_burn' })

  // The analysis is already completed, so the job runs straight away and the workspace opens when it is done.
  await expect(page.getByTestId('processing-view')).toBeVisible()
  await stub.advanceEngagement('eng-stub-1', 6)
  await expect(page.getByTestId('timeline-ruler')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('signal-badge').first()).toHaveText('Template (simulated) · Slow burn')
  await expectNoCrash()
})

test('?analysis= preselects the scene analysis', async ({ page, request, stub }) => {
  await openCreate(page, `?analysis=${AD_SPOT_ID}`)
  const main = page.getByRole('main')
  await expect(main.getByTestId(`analysis-${AD_SPOT_ID}`)).toHaveAttribute('aria-pressed', 'true')
  await expect(main.getByText('Selected Video')).toBeVisible()
  await expect(startButton(page)).toBeDisabled()

  await main.getByRole('radio', { name: /Front-loaded/ }).check()
  await main.getByLabel('Name (optional)').fill('Front-loaded rehearsal')
  await startButton(page).click()
  await expect(page).toHaveURL(/\/engagement\/eng-stub-1$/)
  const created = (await (await request.get(`${stub.origin}/api/v1/engagement/eng-stub-1`)).json()) as EngagementRecord
  expect(created).toMatchObject({ scene_analysis_id: AD_SPOT_ID, display_name: 'Front-loaded rehearsal', signal: { template_id: 'front_loaded' } })
})

test('an unknown ?analysis= id is reported and nothing is preselected', async ({ page }) => {
  await openCreate(page, '?analysis=sa-does-not-exist')
  const main = page.getByRole('main')
  await expect(main.getByText('The scene analysis from the link is not available.')).toBeVisible()
  await expect(main.locator('[data-testid^="analysis-"][aria-pressed="true"]')).toHaveCount(0)
})

test('create from another video with an uploaded BARC file: preview, mapping and offset', async ({ page, stub, request, shot, expectNoCrash }) => {
  // Hold the browser's PUT to the upload URL for a moment so the progress state can be observed.
  await page.route('**/__stub/upload/**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700))
    await route.continue()
  })
  await openCreate(page)
  const main = page.getByRole('main')

  await main.getByRole('tab', { name: 'Other videos' }).click()
  await expect(main.getByText('The video is analysed first, automatically', { exact: false })).toBeVisible()
  await expect(main.getByRole('link', { name: 'Upload new video' })).toHaveAttribute('href', '/uploads')
  await main.getByText('Cricket final highlights (90s)', { exact: true }).click()

  await main.getByRole('radio', { name: /Upload a BARC file/ }).check()
  await expect(main.getByTestId('barc-panel')).toBeVisible()
  await expect(startButton(page)).toBeDisabled()

  await main.getByTestId('barc-file').setInputFiles(BARC_CSV)
  await expect(main.getByTestId('barc-progress')).toContainText(/Uploading barc-kadak-chai-monsoon\.csv/)
  const preview = main.getByTestId('barc-preview')
  await expect(preview).toBeVisible()
  await expect(main.getByTestId('barc-progress')).toHaveCount(0)

  // What the server detected: columns, sample rows, duration and interval, and the default mapping.
  await expect(preview).toContainText('barc-kadak-chai-monsoon.csv · 100 rows')
  await expect(preview.getByTestId('barc-detected')).toHaveText(' · covers 50s, one sample every 0.5s')
  await expect(preview.getByRole('list', { name: 'Detected columns' }).getByRole('listitem')).toHaveCount(7)
  await expect(preview.getByRole('list', { name: 'Detected columns' })).toContainText('Start Time · time')
  await expect(preview.getByRole('list', { name: 'Detected columns' })).toContainText('TVR (%) · metric')
  await expect(preview.getByTestId('barc-sample').locator('tbody tr')).toHaveCount(5)
  await expect(preview.getByTestId('barc-sample').locator('tbody tr').first()).toContainText('20:14:55.0')
  await expect(preview.getByTestId('barc-time-column')).toHaveValue('Start Time')
  await expect(preview.getByTestId('barc-metric')).toHaveValue('TVR (%)')
  await expect(preview.getByTestId('barc-metric').locator('option')).toHaveCount(3)
  await expect(preview.getByTestId('barc-offset')).toHaveValue('0')
  await expect(preview.getByTestId('barc-issues')).toHaveCount(0)
  await expect(startButton(page)).toBeEnabled()

  // An offset the server would reject blocks Start; a valid one enables it again.
  await preview.getByTestId('barc-offset').fill('999999')
  await expect(preview.getByText('Enter a number of seconds between -86400 and 86400.')).toBeVisible()
  await expect(startButton(page)).toBeDisabled()
  await preview.getByTestId('barc-metric').selectOption("Reach ('000s)")
  await preview.getByTestId('barc-offset').fill('-5')
  await expect(startButton(page)).toBeEnabled()
  await shot('engagement-new-barc')

  await startButton(page).click()
  await expect(page).toHaveURL(/\/engagement\/eng-stub-1$/)
  const created = (await (await request.get(`${stub.origin}/api/v1/engagement/eng-stub-1`)).json()) as EngagementRecord
  expect(created.signal).toMatchObject({ kind: 'barc', upload_id: 'upl-stub-1', csv_filename: 'barc-kadak-chai-monsoon.csv', time_column: 'Start Time', metric: "Reach ('000s)", offset_sec: -5 })
  // The cricket upload had no scene analysis: one was created and the report waits for it.
  expect(created).toMatchObject({ source_type: 'upload', source_id: 'upl-fixture-cricket', scene_analysis_id: 'sa-stub-1' })
  await expect(page.getByTestId('waiting-on-analysis')).toBeVisible()
  await expectNoCrash()
})

test('a BARC file whose columns cannot be mapped explains what is missing and keeps Start disabled', async ({ page, shot }) => {
  await useLightTheme(page)
  await openCreate(page)
  const main = page.getByRole('main')
  await main.getByTestId(`analysis-${AD_SPOT_ID}`).click()
  await main.getByRole('radio', { name: /Upload a BARC file/ }).check()

  await main.getByTestId('barc-file').setInputFiles(UNMAPPABLE_CSV)
  const issues = main.getByTestId('barc-issues')
  await expect(issues).toBeVisible()
  await expect(issues).toContainText('No time column was found')
  await expect(issues).toContainText('No numeric metric column was found')
  await expect(main.getByTestId('barc-warnings')).toContainText("No time column was found (expected e.g. 'Start Time', 'time' or 'seconds')")
  await expect(main.getByTestId('barc-sample').locator('tbody tr')).toHaveCount(4)
  await expect(main.getByTestId('barc-time-column')).toHaveCount(0)
  await expect(startButton(page)).toBeDisabled()
  await shot('engagement-new-barc-unmappable-light')

  // A file that is not a CSV is refused before anything is uploaded, and the old preview is gone.
  await main.getByTestId('barc-file').setInputFiles({ name: 'ratings.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('not a csv') })
  await expect(main.getByRole('alert').filter({ hasText: 'Choose a .csv file' })).toBeVisible()
  await expect(main.getByTestId('barc-preview')).toHaveCount(0)
  await expect(startButton(page)).toBeDisabled()

  // Going back to a template makes the form startable again.
  await main.getByRole('radio', { name: /High engagement/ }).check()
  await expect(main.getByTestId('barc-panel')).toHaveCount(0)
  await expect(startButton(page)).toBeEnabled()
})
