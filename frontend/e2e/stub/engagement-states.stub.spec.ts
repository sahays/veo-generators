/**
 * Engagement job states against the stub API: running, waiting on the scene
 * analysis, failed with retry, and a completed report whose prose is missing.
 * Also takes the light-theme and narrow-window screenshots of the workspace.
 * Screenshots are written to `e2e/stub/screenshots/`.
 */
import type { Page } from '@playwright/test'
import { FAILED_ID, NO_PROSE_ID, NO_PROSE_REPORT, RUNNING_ID, BARC_ID, TEMPLATE_ID, WAITING_ID } from './engagementSpecData.ts'
import { expect, test } from './fixtures.ts'
import { box, dragTimes, expectWorkspaceReady } from './timelineHelpers.ts'

async function useLightTheme(page: Page): Promise<void> {
  await page.addInitScript(() => window.localStorage.setItem('theme', 'light'))
}

async function openTab(page: Page, name: RegExp) {
  await page.getByRole('tab', { name }).click()
  const panel = page.getByRole('tabpanel', { name })
  await expect(panel).toBeVisible()
  return panel
}

test('a running job shows the stage stepper and opens the workspace when it completes', async ({ page, stub, shot, expectNoCrash }) => {
  await stub.advanceEngagement(RUNNING_ID, 2)
  await page.goto(`/engagement/${RUNNING_ID}`)
  const progress = page.getByTestId('processing-view')
  await expect(progress).toBeVisible({ timeout: 60_000 })

  // waiting → signal → stats → explain → recommend; the first two are done, statistics is running.
  await expect(progress.locator('li')).toHaveCount(5)
  await expect(progress.locator('li[data-stage="waiting"]')).toHaveAttribute('data-state', 'done')
  await expect(progress.locator('li[data-stage="signal"]')).toHaveAttribute('data-state', 'done')
  await expect(progress.locator('li[data-state="active"]')).toHaveCount(1)
  await expect(progress.getByRole('status')).toContainText(/\d+% complete/)
  await expect(page.locator('header').getByTestId('signal-badge')).toHaveText('Template (simulated) · Slow burn')
  await expect(page.getByTestId('export-menu')).toHaveCount(0)
  await shot('engagement-running')

  // Polling picks up each later stage, then the finished report.
  await stub.advanceEngagement(RUNNING_ID, 6)
  await expectWorkspaceReady(page)
  await expect(page.getByTestId('processing-view')).toHaveCount(0)
  await expect(page.getByTestId('export-menu')).toBeVisible()
  await expectNoCrash()
})

test('a job waiting on its scene analysis says so, links to it, and starts when the analysis is done', async ({ page, stub, shot }) => {
  await page.goto(`/engagement/${WAITING_ID}`)
  const progress = page.getByTestId('processing-view')
  await expect(progress).toBeVisible({ timeout: 60_000 })

  const waiting = progress.locator('li[data-stage="waiting"]')
  await expect(waiting).toHaveAttribute('data-state', 'active')
  await expect(waiting).toContainText('Waiting for scene analysis')
  await expect(progress.getByRole('status')).toHaveText('Not started yet: waiting for the scene analysis')
  const note = page.getByTestId('waiting-on-analysis')
  await expect(note).toContainText('Waiting for the scene analysis of this video.')
  await expect(note.getByTestId('scene-analysis-link')).toHaveAttribute('href', '/scene-analysis/sa-fixture-running')
  await expect(page.getByTestId('open-scene-analysis')).toHaveAttribute('href', '/scene-analysis/sa-fixture-running')
  await shot('engagement-waiting')

  // Finish the scene analysis: the next polls take the engagement job out of waiting and through its stages.
  await stub.advanceSceneAnalysis('sa-fixture-running', 8)
  await expect(page.getByTestId('waiting-on-analysis')).toHaveCount(0, { timeout: 20_000 })
  await expect(waiting).toHaveAttribute('data-state', /done|waiting/)
  await stub.advanceEngagement(WAITING_ID, 6)
  await expectWorkspaceReady(page)
})

test('a failed job shows the error and Retry restarts it', async ({ page, shot }) => {
  await page.goto(`/engagement/${FAILED_ID}`)
  const progress = page.getByTestId('processing-view')
  const alert = progress.getByRole('alert')
  await expect(alert).toBeVisible({ timeout: 60_000 })
  await expect(alert).toContainText('The signal CSV could not be downloaded. It may have been deleted from Files.')
  await expect(progress.locator('li[data-stage="signal"]')).toHaveAttribute('data-state', 'failed')
  await expect(page.locator('header').getByTestId('signal-badge')).toHaveText('BARC · barc-week-28-evening.csv')
  await expect(page.getByTestId('open-scene-analysis')).toHaveAttribute('href', '/scene-analysis/sa-fixture-ad-spot')
  await shot('engagement-failed')

  await progress.getByRole('button', { name: 'Retry' }).click()
  await expect(progress.getByRole('alert')).toHaveCount(0)
  await expect(progress.getByRole('status')).toBeVisible()
})

test('a report without prose shows its numbers and clear empty states, never blank cards', async ({ page, shot, expectNoCrash }) => {
  await page.goto(`/engagement/${NO_PROSE_ID}`)
  await expectWorkspaceReady(page)

  // Overview: the figures are there; the headline's place says why it is empty.
  const overview = page.getByRole('tabpanel', { name: /Overview/ })
  await expect(overview.getByTestId('empty-prose')).toContainText('No headline was written.')
  await expect(overview.getByTestId('report-headline')).toHaveCount(0)
  await expect(overview.getByTestId('kpi-peak')).toContainText('80.7')
  await expect(overview.getByTestId('segment-chart').locator('.recharts-bar-rectangle')).toHaveCount(9)
  await shot('engagement-no-prose-overview')

  // Peaks & Valleys: one notice, and every card has a title built from its kind and time.
  const peaks = await openTab(page, /Peaks & Valleys/)
  await expect(peaks.getByTestId('empty-prose')).toContainText('Explanations were not generated.')
  const cards = peaks.locator('[data-testid^="extremum-"]')
  await expect(cards).toHaveCount(NO_PROSE_REPORT.extrema.length)
  await expect(peaks.getByTestId('extremum-peak-1')).toContainText('Peak at 0:29')
  await expect(peaks.getByTestId('extremum-peak-1')).toContainText('No explanation was written for this moment.')
  await expect(peaks.getByTestId('extremum-peak-1')).toContainText('+59.8%')
  for (const text of await cards.allInnerTexts()) expect(text.trim().length).toBeGreaterThan(40)
  await shot('engagement-no-prose-peaks')

  // Drivers are numbers only, so they are complete.
  const drivers = await openTab(page, /Drivers/)
  await expect(drivers.getByTestId('driver-character:asha')).toContainText('+3.8%')

  // Recommendations: a single explained empty state with the worker's note.
  const recs = await openTab(page, /Recommendations/)
  await expect(recs.getByTestId('empty-prose')).toContainText('No recommendations were written.')
  await expect(recs.getByTestId('empty-prose')).toContainText('Recommendations could not be generated')
  await expect(recs.getByRole('region', { name: 'Do more' })).toHaveCount(0)
  await shot('engagement-no-prose-recommendations')
  await expectNoCrash()
})

test('light theme: template and BARC workspaces, tabs and job states', async ({ page, stub, shot }) => {
  await useLightTheme(page)
  await page.goto(`/engagement/${TEMPLATE_ID}`)
  await expectWorkspaceReady(page)
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await shot('engagement-workspace-template-light')

  const peaks = await openTab(page, /Peaks & Valleys/)
  await peaks.getByTestId('extremum-valley-1').click()
  await shot('engagement-peaks-light')
  const drivers = await openTab(page, /Drivers/)
  await drivers.getByTestId('driver-character:asha').click()
  await drivers.getByTestId('driver-emotion:humor').click()
  await shot('engagement-drivers-light')
  await openTab(page, /Recommendations/)
  await shot('engagement-recommendations-light')

  await page.goto(`/engagement/${BARC_ID}`)
  await expectWorkspaceReady(page)
  await shot('engagement-workspace-barc-light')
  await openTab(page, /Data/)
  await shot('engagement-data-light')

  await page.goto(`/engagement/${NO_PROSE_ID}`)
  await expectWorkspaceReady(page)
  await openTab(page, /Recommendations/)
  await shot('engagement-no-prose-light')

  await stub.advanceEngagement(RUNNING_ID, 3)
  await page.goto(`/engagement/${RUNNING_ID}`)
  await expect(page.getByTestId('processing-view')).toBeVisible()
  await shot('engagement-running-light')
  await page.goto(`/engagement/${WAITING_ID}`)
  await expect(page.getByTestId('waiting-on-analysis')).toBeVisible()
  await shot('engagement-waiting-light')
  await page.goto(`/engagement/${FAILED_ID}`)
  await expect(page.getByTestId('processing-view').getByRole('alert')).toBeVisible()
  await shot('engagement-failed-light')
})

test('a narrow window keeps the lanes aligned and the panels readable', async ({ page, shot }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await page.goto(`/engagement/${TEMPLATE_ID}`)
  await expectWorkspaceReady(page)
  const plots = await page.locator('[data-lane] > div:nth-child(2)').evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().width)))
  expect(new Set(plots).size).toBe(1)
  expect(plots[0]).toBeGreaterThan(300)
  const surface = await page.locator('[data-testid="curve-plot"] svg.recharts-surface').evaluate((node) => Math.round(node.getBoundingClientRect().width))
  expect(Math.abs(surface - plots[0])).toBeLessThanOrEqual(1)
  await expect(page.getByTestId('moment-panel')).toBeVisible()
  await expect(page.getByTestId('range-inspector')).toBeVisible()
  await shot('engagement-workspace-narrow')

  // The panels are stacked above the timeline here; selecting a range must still not move the ruler.
  const ruler = page.getByTestId('timeline-ruler')
  await ruler.scrollIntoViewIfNeeded()
  const before = await box(ruler)
  await dragTimes(page, ruler, 10, 30, true)
  await expect(page.getByTestId('range-inspector').getByTestId('range-average')).toBeVisible()
  expect((await box(ruler)).y).toBe(before.y)
})
