/**
 * Engagement workspace against the stub API: the curve lane's alignment with
 * the other lanes, seeking from the curve, peak cards, driver shading, the
 * range inspector, metric toggles, tabs, export and deep links.
 * Screenshots are written to `e2e/stub/screenshots/`.
 */
import type { Page } from '@playwright/test'
import type { EngagementReport } from '../../src/types/insights.ts'
import { AD_SPOT_ID } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { BARC_ID, BARC_REPORT, TEMPLATE_ID, TEMPLATE_REPORT, extremum, meanBetween, primaryPoints, shown, valueAt } from './engagementSpecData.ts'
import { expect, test } from './fixtures.ts'
import { DURATION, box, clickRulerAt, clientRect, downloadText, dragTimes, expectWorkspaceReady, videoState, visibleRange, xOfTime } from './timelineHelpers.ts'

const CURVE_PLOT = '[data-lane="engagement"] > div:nth-child(2)'
const CURVE_DOTS = '[data-testid="curve-plot"] .recharts-reference-dot circle'

async function openReport(page: Page, id: string, query = ''): Promise<void> {
  await page.goto(`/engagement/${id}${query}`)
  await expectWorkspaceReady(page)
  await expect(page.locator(CURVE_DOTS).first()).toBeVisible()
}

const currentTime = (page: Page): Promise<number> => videoState(page).then((v) => v.currentTime)

/** Centre x of every element matching `selector`, in ascending order. */
async function centresX(page: Page, selector: string): Promise<number[]> {
  const xs = await page.locator(selector).evaluateAll((nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return rect.left + rect.width / 2
    }),
  )
  return xs.sort((a, b) => a - b)
}

async function openTab(page: Page, name: RegExp) {
  await page.getByRole('tab', { name }).click()
  const panel = page.getByRole('tabpanel', { name })
  await expect(panel).toBeVisible()
  return panel
}

test('template report: header, honest labelling and lanes on one scale', async ({ page, shot, expectNoCrash }) => {
  await openReport(page, TEMPLATE_ID)

  await expect(page.locator('header').getByRole('button', { name: 'Monsoon spot — Jumpy template' })).toBeVisible()
  await expect(page.locator('header').getByTestId('signal-badge')).toHaveText('Template (simulated) · Jumpy')
  await expect(page.getByTestId('open-scene-analysis')).toHaveAttribute('href', `/scene-analysis/${AD_SPOT_ID}`)
  // A persistent "Template (simulated)" badge sits on the curve itself.
  await expect(page.getByTestId('curve-plot').getByTestId('signal-badge')).toHaveText('Template (simulated)')
  await expect(page.getByTestId('moment-value')).toContainText(shown(primaryPoints(TEMPLATE_REPORT)[0][1]))

  // Every lane plot, the curve's included, starts at the same x and has the same width; so does the minimap.
  const plots = await page.locator('[data-lane] > div:nth-child(2)').evaluateAll((nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { left: Math.round(rect.left * 10) / 10, width: Math.round(rect.width * 10) / 10 }
    }),
  )
  expect(plots.length).toBeGreaterThanOrEqual(8)
  expect(new Set(plots.map((p) => `${p.left}/${p.width}`)).size).toBe(1)
  const track = await box(page.getByTestId('minimap-track'))
  expect(Math.abs(track.x - plots[0].left)).toBeLessThan(0.6)
  expect(Math.abs(track.width - plots[0].width)).toBeLessThan(0.6)

  await expectNoCrash()
  await shot('engagement-workspace-template')
})

test('the recharts curve maps time to the same x as the ruler and the marker lane, also when zoomed', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const plot = await box(page.locator(CURVE_PLOT))
  const ruler = await box(page.getByTestId('timeline-ruler'))

  // The chart's drawing surface is exactly the lane's plot box: no margins, no offset.
  const surface = await box(page.locator('[data-testid="curve-plot"] svg.recharts-surface'))
  expect(Math.abs(surface.x - plot.x)).toBeLessThan(0.6)
  expect(Math.abs(surface.width - plot.width)).toBeLessThan(0.6)
  expect(Math.abs(ruler.x - plot.x)).toBeLessThan(0.6)

  // Known times: the chart draws a dot at each extremum. Each must sit where the ruler puts that time.
  const times = TEMPLATE_REPORT.extrema.map((item) => item.time_sec).sort((a, b) => a - b)
  const dots = await centresX(page, CURVE_DOTS)
  expect(dots).toHaveLength(times.length)
  dots.forEach((x, i) => expect(Math.abs(x - xOfTime(ruler, times[i])), `dot ${i} at ${times[i]} s`).toBeLessThan(0.75))

  // The stepped area starts at 0 s and its last step ends at the end of the video: both plot edges.
  const area = await clientRect(page.locator('[data-testid="curve-plot"] .recharts-area-curve'))
  expect(Math.abs(area.x - plot.x)).toBeLessThan(1)
  expect(Math.abs(area.x + area.width - (plot.x + plot.width))).toBeLessThan(1)

  // The marker lane uses the kit's scale; every single marker has a chart dot at the same x.
  const markers = await centresX(page, '[data-lane="extrema"] [data-tl-item]:not([aria-label*="markers from"])')
  expect(markers.length).toBeGreaterThan(4)
  markers.forEach((x) => expect(Math.min(...dots.map((dot) => Math.abs(dot - x))), `marker at x=${x}`).toBeLessThan(1))

  // Zoom in about the cursor, seek to the main peak: the clock-driven playhead lands on that peak's dot.
  const peak = extremum(TEMPLATE_REPORT, 'peak-1')
  await page.mouse.move(xOfTime(plot, peak.time_sec + 2), plot.y + plot.height / 2)
  await page.mouse.wheel(0, -700)
  await expect.poll(() => visibleRange(page).then((r) => r.end - r.start)).toBeLessThan(15)
  await page.locator('[data-lane="extrema"] [data-tl-item][aria-label^="Peak: Spike on the knees joke"]').click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(peak.time_sec, 1)
  const head = await box(page.getByTestId('timeline-playhead'))
  const zoomedDots = await centresX(page, CURVE_DOTS)
  expect(Math.min(...zoomedDots.map((x) => Math.abs(x - head.x)))).toBeLessThan(1)
  const zoomedSurface = await box(page.locator('[data-testid="curve-plot"] svg.recharts-surface'))
  expect(Math.abs(zoomedSurface.x - plot.x)).toBeLessThan(0.6)
  await shot('engagement-workspace-zoomed')
})

test('click or drag on the curve scrubs at any time without pausing; playback does not redraw the curve', async ({ page }) => {
  await openReport(page, TEMPLATE_ID)
  const points = primaryPoints(TEMPLATE_REPORT)
  const curve = page.getByTestId('curve-plot')
  const plot = await box(curve)

  // 20.6 s is between samples: the seek goes exactly there and the panel shows the value holding at that time.
  await page.mouse.click(xOfTime(plot, 20.6), plot.y + plot.height / 2)
  await expect.poll(() => currentTime(page)).toBeCloseTo(20.6, 1)
  expect((await videoState(page)).paused).toBe(true)
  await expect(page.getByTestId('moment-value')).toContainText(shown(valueAt(points, 20.6)))
  await expect(page.getByTestId('moment-panel')).toContainText('Pour and first sip')

  // Dragging scrubs (it does not pan the timeline).
  await dragTimes(page, curve, 10, 12.5)
  await expect.poll(() => currentTime(page)).toBeCloseTo(12.5, 1)
  expect(await visibleRange(page)).toEqual({ start: 0, end: DURATION })
  await expect(page.getByTestId('moment-value')).toContainText(shown(valueAt(points, 12.5)))

  // While playing, a click on the curve seeks and playback carries on; the curve lane's DOM is left alone.
  await page.getByTestId('player-play').click()
  await expect.poll(() => videoState(page).then((v) => v.paused)).toBe(false)
  await page.locator('[data-lane="engagement"]').evaluate((lane) => {
    const win = window as unknown as { __curveMutations: number }
    win.__curveMutations = 0
    new MutationObserver((records) => (win.__curveMutations += records.length)).observe(lane, { subtree: true, childList: true, attributes: true, characterData: true })
  })
  await page.mouse.click(xOfTime(plot, 30), plot.y + plot.height / 2)
  await page.waitForTimeout(1200)
  const after = await videoState(page)
  expect(after.paused).toBe(false)
  expect(after.currentTime).toBeGreaterThan(30.5)
  expect(await page.evaluate(() => (window as unknown as { __curveMutations: number }).__curveMutations)).toBe(0)
  await page.getByTestId('player-play').click()
})

test('a peak card seeks, zooms the timeline to the moment and selects it; the card nearest the playhead is marked', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const panel = await openTab(page, /Peaks & Valleys/)
  const peak = extremum(TEMPLATE_REPORT, 'peak-1')
  const cards = panel.locator('[data-testid^="extremum-"]')
  await expect(cards).toHaveCount(TEMPLATE_REPORT.extrema.length)

  const card = panel.getByTestId('extremum-peak-1')
  await expect(card).toContainText('Spike on the knees joke')
  await expect(card).toContainText(shown(peak.value))
  await expect(card).toContainText('+59.8%')
  await card.click()

  await expect.poll(() => currentTime(page)).toBeCloseTo(peak.time_sec, 1)
  // viewport.showRange pads the extremum's window by 15% on each side.
  const pad = (peak.window.end_sec - peak.window.start_sec) * 0.15
  const view = await visibleRange(page)
  expect(view.start).toBeCloseTo(peak.window.start_sec - pad, 0)
  expect(view.end).toBeCloseTo(peak.window.end_sec + pad, 0)
  await expect(card).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[data-lane="extrema"] [data-tl-item][aria-pressed="true"]')).toHaveCount(1)
  await expect(card).toHaveAttribute('data-nearest', 'true')
  await expect(panel.locator('[data-nearest="true"]')).toHaveCount(1)
  await expect(page).toHaveURL(/sel=peak-1/)
  await shot('engagement-peaks')

  // Move the playhead next to the deepest valley: the highlight follows it.
  await page.getByRole('button', { name: 'Fit whole video' }).click()
  await clickRulerAt(page, 18.3)
  await expect(panel.getByTestId('extremum-valley-1')).toHaveAttribute('data-nearest', 'true')
  await expect(card).toHaveAttribute('data-nearest', 'false')
  await expect(panel.locator('[data-nearest="true"]')).toHaveCount(1)
})

test('selected drivers are shaded on the curve and compared in the Drivers lane', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const panel = await openTab(page, /Drivers/)
  const plot = await box(page.locator(CURVE_PLOT))
  const asha = TEMPLATE_REPORT.influence.find((entry) => entry.key === 'character:asha')
  if (!asha) throw new Error('fixture has no character:asha')

  // Honest labelling: associations, grouped by kind, low support marked in words.
  await expect(panel.getByTestId('association-note')).toContainText('Associations, not causes.')
  for (const kind of ['character', 'object', 'location', 'emotion', 'event']) {
    await expect(panel.getByTestId(`driver-group-${kind}`)).toBeVisible()
  }
  await expect(panel.getByTestId('driver-object:offer qr code')).toContainText('Low support')
  await expect(panel.getByTestId('driver-character:asha')).toContainText('+3.8%')
  await expect(panel.getByTestId('driver-group-character').locator('.recharts-bar-rectangle')).toHaveCount(2)
  await expect(page.getByTestId('driver-shading')).toHaveCount(0)

  // Selecting a driver shades each of its ranges on the curve, at the ranges' own times.
  const toggle = panel.getByTestId('driver-character:asha')
  const toggleY = (await box(toggle)).y
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  const shades = page.locator('[data-testid="driver-shading"] rect[data-driver="character:asha"]')
  await expect(shades).toHaveCount(asha.ranges.length)
  const first = await clientRect(shades.first())
  expect(Math.abs(first.x - xOfTime(plot, asha.ranges[0].start_sec))).toBeLessThan(1)
  expect(Math.abs(first.x + first.width - xOfTime(plot, asha.ranges[0].end_sec))).toBeLessThan(1)
  await expect(page.locator('[data-lane="drivers"]')).toContainText('Drivers (1)')
  // The lane has a fixed height, so the toggle that was just clicked has not moved.
  expect((await box(toggle)).y).toBe(toggleY)

  // A second driver (toggled from the keyboard) gets its own row and colour.
  await panel.getByTestId('driver-character:mr. rao').focus()
  await page.keyboard.press('Space')
  await expect(panel.getByTestId('driver-character:mr. rao')).toHaveAttribute('aria-pressed', 'true')
  const bars = page.locator('[data-lane="drivers"] rect[data-driver]')
  await expect(bars).toHaveCount(3)
  const rows = await bars.evaluateAll((nodes) => nodes.map((node) => ({ driver: node.getAttribute('data-driver'), y: node.getAttribute('y'), fill: node.getAttribute('fill') })))
  expect(new Set(rows.map((row) => row.y)).size).toBe(2)
  expect(new Set(rows.map((row) => row.fill)).size).toBe(2)
  await expect(page.locator('[data-testid="driver-shading"] rect')).toHaveCount(3)
  await shot('engagement-drivers')

  // The selection summary removes one; the other stays.
  await panel.getByRole('button', { name: 'Stop shading Asha' }).click()
  await expect(page.locator('[data-testid="driver-shading"] rect')).toHaveCount(1)
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
})

test('Shift-drag on the ruler opens the range inspector with the range average against the overall average', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const inspector = page.getByTestId('range-inspector')
  await expect(inspector).toContainText('Shift-drag on the ruler or the curve')
  const inspectorBox = await box(inspector)
  const timelineY = (await box(page.getByTestId('timeline-ruler'))).y

  await dragTimes(page, page.getByTestId('timeline-ruler'), 18, 32, true)
  await expect(page.getByTestId('timeline-selection')).toBeVisible()
  await expect(inspector.getByTestId('range-span')).toContainText(/0:1[78]\.\d – 0:3[12]\.\d \(14s\)/)

  // The average comes from prefix sums in the app; here it is recomputed sample by sample.
  const expected = meanBetween(primaryPoints(TEMPLATE_REPORT), TEMPLATE_REPORT.signal.interval_sec, 18, 32)
  const shownAverage = Number((await inspector.getByTestId('range-average').locator('span').first().innerText()).replace(/,/g, ''))
  expect(Math.abs(shownAverage - expected)).toBeLessThan(0.25)
  await expect(inspector.getByTestId('range-average')).toContainText(`Overall average ${shown(TEMPLATE_REPORT.stats.avg)}`)
  const onScreen = inspector.getByRole('list', { name: 'On screen in this range' })
  await expect(onScreen).toContainText('Asha')
  await expect(onScreen).toContainText('Mr. Rao')
  await expect(inspector.getByRole('list', { name: 'Cues in this range' }).getByRole('listitem')).toHaveCount(5)
  await expect(inspector).toContainText('more')

  // The inspector sits next to the player at a fixed size: filling it does not move the timeline.
  expect(await box(inspector)).toEqual(inspectorBox)
  expect((await box(page.getByTestId('timeline-ruler'))).y).toBe(timelineY)
  await shot('engagement-range-inspector')

  await inspector.getByRole('button', { name: 'Zoom to range' }).click()
  const view = await visibleRange(page)
  expect(view.start).toBeCloseTo(18 - 14 * 0.15, 0)
  expect(view.end).toBeCloseTo(32 + 14 * 0.15, 0)
  await inspector.getByRole('button', { name: 'Clear' }).click()
  await expect(page.getByTestId('timeline-selection')).toHaveCount(0)

  // Shift-drag on the curve selects a range too, and a clicked segment is summarised the same way.
  await page.getByRole('button', { name: 'Fit whole video' }).click()
  await dragTimes(page, page.getByTestId('curve-plot'), 5, 9, true)
  await expect(inspector.getByTestId('range-span')).toContainText('(4s)')
  await page.locator('[data-lane="segments"] [data-tl-item]').nth(6).click()
  await expect(inspector).toContainText('Shared laughter on the balcony')
  await expect(inspector.getByTestId('range-span')).toContainText('0:28.0 – 0:33.5 (5.5s)')
})

/** Hover-card readings at `timeSec`, e.g. `TVR (%) 1.63% +7.6%`. */
async function hoverReadings(page: Page, timeSec: number): Promise<string[]> {
  const plot = await box(page.locator(CURVE_PLOT))
  await page.mouse.move(xOfTime(plot, timeSec), plot.y + plot.height / 2)
  const items = page.getByTestId('hover-metrics').getByRole('listitem')
  await expect(items.first()).toBeVisible()
  return (await items.allInnerTexts()).map((text) => text.replace(/\s+/g, ' ').trim())
}

function metricPoints(report: EngagementReport, key: string) {
  const metric = report.metrics.find((item) => item.key === key)
  if (!metric) throw new Error(`fixture has no metric ${key}`)
  return metric.points
}

test('BARC report: metric toggles, each metric on its own scale, true values in the hover card', async ({ page, shot, expectNoCrash }) => {
  await openReport(page, BARC_ID)
  const curve = page.getByTestId('curve-plot')
  const toggles = page.getByTestId('curve-toggles')
  const toggle = (name: string) => toggles.getByRole('button', { name, exact: false })

  // Measured data: no "simulated" badge on the curve and no template note on the tabs.
  await expect(page.locator('header').getByTestId('signal-badge')).toHaveText('BARC · barc-kadak-chai-monsoon.csv')
  await expect(curve.getByTestId('signal-badge')).toHaveCount(0)
  await expect(page.getByTestId('simulated-note')).toHaveCount(0)

  // Three metrics and the smoothed line, all on: one area, two dashed lines and the smoothed line.
  await expect(toggles.getByRole('button')).toHaveCount(4)
  await expect(toggles.locator('[aria-pressed="true"]')).toHaveCount(4)
  await expect(curve.locator('.recharts-area-curve')).toHaveCount(1)
  await expect(curve.locator('.recharts-line-curve')).toHaveCount(3)

  // The hover card shows every visible metric in its own units, although they share one 0..1 drawing scale.
  const at = 20.2
  const tvr = shown(valueAt(metricPoints(BARC_REPORT, 'tvr'), at), '%')
  const impressions = shown(valueAt(metricPoints(BARC_REPORT, 'impressions_000s'), at))
  const reach = shown(valueAt(metricPoints(BARC_REPORT, 'reach_000s'), at))
  const readings = await hoverReadings(page, at)
  expect(readings).toHaveLength(3)
  expect(readings[0]).toContain(`TVR (%) ${tvr}`)
  expect(readings[1]).toBe(`Impressions ('000s) ${impressions}`)
  expect(readings[2]).toBe(`Reach ('000s) ${reach}`)
  await expect(page.getByTestId('timeline-hover-card')).toContainText('Pour and first sip')
  await shot('engagement-workspace-barc')

  // Hiding a metric removes its line and its reading.
  await toggle('Impressions').click()
  await expect(toggle('Impressions')).toHaveAttribute('aria-pressed', 'false')
  await expect(curve.locator('.recharts-line-curve')).toHaveCount(2)
  expect(await hoverReadings(page, at)).toHaveLength(2)

  // The smoothed line has its own switch; hiding the primary metric takes its average line and dots with it.
  await toggle('Smoothed').click()
  await expect(curve.locator('.recharts-line-curve')).toHaveCount(1)
  await toggle('TVR').click()
  await expect(curve.locator('.recharts-area-curve')).toHaveCount(0)
  await expect(page.locator(CURVE_DOTS)).toHaveCount(0)
  await expect(curve.locator('.recharts-reference-line')).toHaveCount(0)

  // The last visible metric cannot be hidden.
  await toggle('Reach').click()
  await expect(toggle('Reach')).toHaveAttribute('aria-pressed', 'true')
  await expect(curve.locator('.recharts-line-curve')).toHaveCount(1)
  await expectNoCrash()
})

test('BARC report: the Data tab shows the mapping, the offset and a windowed points table', async ({ page, shot }) => {
  await openReport(page, BARC_ID)
  const panel = await openTab(page, /Data/)
  const signal = panel.getByRole('region', { name: 'Signal', exact: true })
  await expect(signal).toContainText('BARC · barc-kadak-chai-monsoon.csv')
  await expect(signal).toContainText('Start Time')
  await expect(signal).toContainText('TVR (%)')
  await expect(signal).toContainText('-5 s added to every timestamp')
  await expect(signal).toContainText('90, one every 0.5s')

  // 90 samples, but only the rows near the scroll position are in the DOM.
  const table = panel.getByTestId('points-table')
  await expect(table).toHaveAttribute('aria-label', 'Signal points, 90 rows')
  const mounted = await table.locator('tbody tr:not([aria-hidden])').count()
  expect(mounted).toBeGreaterThan(5)
  expect(mounted).toBeLessThan(60)
  await expect(table.getByRole('button', { name: 'Go to 0:44.5' })).toHaveCount(0)
  await table.evaluate((node) => node.scrollTo(0, node.scrollHeight))
  await expect(table.getByRole('button', { name: 'Go to 0:44.5' })).toBeVisible()
  await expect(table.locator('thead')).toContainText("TVR (%) (smoothed)")
  await shot('engagement-data')

  // A row's time seeks there.
  await table.getByRole('button', { name: 'Go to 0:44.5' }).click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(44.5, 1)
})

test('tabs: overview KPIs and segments, recommendations with evidence chips and segment fixes', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const { kpis, recommendations } = TEMPLATE_REPORT

  // Overview is the default tab.
  const overview = page.getByRole('tabpanel', { name: /Overview/ })
  await expect(overview.getByTestId('simulated-note')).toContainText('illustrative template, not audience measurement')
  await expect(overview.getByTestId('report-headline')).toHaveText(recommendations.headline)
  await expect(overview.getByTestId('kpi-average')).toContainText(shown(kpis.avg))
  await expect(overview.getByTestId('kpi-hook-average')).toContainText('first 4.5s')
  await overview.getByRole('button', { name: 'Peak: go to 0:29' }).click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(29, 1)
  await expect(overview.getByTestId('segment-chart').locator('.recharts-bar-rectangle')).toHaveCount(9)
  // A segment from the ranked list: seek to its start and zoom the timeline to it.
  await overview.getByTestId('segment-ranking').getByRole('button', { name: /The kettle goes on/ }).click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(7.5, 1)
  const view = await visibleRange(page)
  expect(view.start).toBeCloseTo(7.5 - 4.5 * 0.15, 0)
  expect(view.end).toBeCloseTo(12 + 4.5 * 0.15, 0)
  await page.getByRole('button', { name: 'Fit whole video' }).click()

  // The template note is on every tab with numbers derived from the curve, and not on Data.
  for (const name of [/Peaks & Valleys/, /Drivers/, /Recommendations/]) {
    const panel = await openTab(page, name)
    await expect(panel.getByTestId('simulated-note')).toBeVisible()
  }

  const recs = page.getByRole('tabpanel', { name: /Recommendations/ })
  await expect(recs).toContainText(recommendations.headline)
  const doMore = recs.getByRole('region', { name: 'Do more' })
  await expect(doMore.getByRole('listitem')).toHaveCount(recommendations.do_more.length)
  await expect(doMore).toContainText('Give the humour more room')
  await expect(doMore).toContainText('Medium expected lift')
  await expect(doMore.getByTestId('recommendation-evidence').first()).toContainText('Evidence (association):')
  await shot('engagement-recommendations')

  // An evidence chip seeks to where the driver appears; the driver can be shaded from here too.
  await doMore.getByRole('button', { name: 'Go to 0:24, where Humor appears' }).click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(24.5, 1)
  await doMore.getByTestId('recommendation-evidence').first().getByRole('button', { name: 'Shade on timeline' }).click()
  await expect(page.locator('[data-testid="driver-shading"] rect[data-driver="emotion:humor"]')).toHaveCount(1)

  // A segment fix goes to its segment.
  const fix = recs.getByTestId('segment-fix-seg-9')
  await expect(fix).toContainText('Tagline and call to action')
  await fix.getByRole('button', { name: 'Go to 0:39' }).click()
  await expect.poll(() => currentTime(page)).toBeCloseTo(39, 1)

  const data = await openTab(page, /Data/)
  await expect(data.getByTestId('simulated-note')).toHaveCount(0)
  await expect(data).toContainText('Template (simulated) · Jumpy')
})

test('export menu downloads the report JSON and the three CSVs', async ({ page }) => {
  await openReport(page, TEMPLATE_ID)
  const download = async (item: RegExp) => {
    await page.getByTestId('export-menu').click()
    const [file] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: item }).click()])
    return { name: file.suggestedFilename(), text: await downloadText(file) }
  }

  const json = await download(/Report \(JSON\)/)
  expect(json.name).toBe('monsoon-spot-jumpy-template-engagement-report.json')
  expect(JSON.parse(json.text)).toEqual(TEMPLATE_REPORT)

  const curve = await download(/Curve \(45 points\)/)
  expect(curve.name).toBe('monsoon-spot-jumpy-template-curve.csv')
  const curveRows = curve.text.split('\r\n')
  expect(curveRows[0]).toBe('time_sec,Engagement index,Engagement index (smoothed)')
  expect(curveRows[1]).toBe('0,63.06,63.06')
  expect(curveRows).toHaveLength(47)

  const extrema = await download(/Peaks, valleys and drops \(13\)/)
  expect(extrema.name).toBe('monsoon-spot-jumpy-template-peaks-valleys-drops.csv')
  expect(extrema.text.split('\r\n')[1].startsWith('peak-1,peak,29,80.74,59.81,')).toBe(true)
  expect(extrema.text.split('\r\n')).toHaveLength(15)

  const drivers = await download(/Drivers \(23\)/)
  expect(drivers.name).toBe('monsoon-spot-jumpy-template-drivers.csv')
  expect(drivers.text.split('\r\n')[0]).toBe('key,name,kind,avg_during,delta_pct,coverage_sec,coverage_pct,low_support,ranges_sec')
  expect(drivers.text.split('\r\n')).toHaveLength(25)
})

test('a link with ?t= and ?sel=<extremum id> reopens on that moment', async ({ page }) => {
  await openReport(page, TEMPLATE_ID, '?t=36&sel=valley-1')
  await expect.poll(() => currentTime(page)).toBeCloseTo(36, 1)
  await expect(page.locator('[data-lane="extrema"] [data-tl-item][aria-pressed="true"]')).toHaveCount(1)
  const panel = await openTab(page, /Peaks & Valleys/)
  await expect(panel.getByTestId('extremum-valley-1')).toHaveAttribute('aria-pressed', 'true')
  // The playhead is at 36 s, where a peak and the steepest drop both sit; the earlier-listed one is marked.
  await expect(panel.locator('[data-nearest="true"]')).toHaveCount(1)
})

test('markers and cards are reachable from the keyboard', async ({ page, shot }) => {
  await openReport(page, TEMPLATE_ID)
  const markers = page.locator('[data-lane="extrema"] [data-tl-item]')
  await markers.first().focus()
  await page.keyboard.press('ArrowRight')
  await expect(markers.nth(1)).toBeFocused()
  await page.keyboard.press('Enter')
  const label = await markers.nth(1).getAttribute('aria-label')
  expect(label).toMatch(/^(Peak|Valley|Drop): /)
  await expect(markers.nth(1)).toHaveAttribute('aria-pressed', 'true')
  await shot('engagement-keyboard-focus')

  const panel = await openTab(page, /Peaks & Valleys/)
  await panel.getByTestId('extremum-peak-2').focus()
  await page.keyboard.press('Enter')
  await expect.poll(() => currentTime(page)).toBeCloseTo(extremum(TEMPLATE_REPORT, 'peak-2').time_sec, 1)
})
