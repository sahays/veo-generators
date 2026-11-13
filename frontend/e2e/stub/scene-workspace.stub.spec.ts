/**
 * Scene Analysis workspace against the stub API: screenshots plus the
 * interactions the timeline kit promises (seek, zoom, pan, tabs, pins, lane
 * toggles, keyboard, deep links, export, job progress).
 * Screenshots are written to `e2e/stub/screenshots/`.
 */
import type { Page } from '@playwright/test'
import { AD_SPOT_ID } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { expect, test } from './fixtures.ts'
import { DURATION, box, clickRulerAt, expectWorkspaceReady, videoState, visibleRange } from './timelineHelpers.ts'

const WORKSPACE_URL = `/scene-analysis/${AD_SPOT_ID}`

async function openWorkspace(page: Page, query = ''): Promise<void> {
  await page.goto(`${WORKSPACE_URL}${query}`)
  await expectWorkspaceReady(page)
}

test('completed workspace renders player, inspector, aligned lanes and minimap', async ({ page, shot, expectNoCrash, pageErrors }) => {
  await openWorkspace(page)

  await expect(page.getByRole('heading', { name: 'Kadak Chai — Monsoon', exact: true })).toBeVisible()
  await expect(page.getByTestId('run-engagement')).toHaveAttribute('href', `/engagement/new?analysis=${AD_SPOT_ID}`)
  await expect(page.getByTestId('now-strip')).toContainText('Rain on the window')
  await expect(page.getByTestId('screen-time-chart').locator('.recharts-bar-rectangle')).toHaveCount(8)
  await expect(page.getByTestId('emotion-chart').locator('.recharts-area-curve')).toHaveCount(1)

  // Every lane plot starts at the same x and has the same width as the ruler's.
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
  expect(pageErrors).toEqual([])
  await shot('scene-workspace-overview')
})

test('clicking the ruler seeks without pausing, scrolling the page or re-rendering lanes', async ({ page, shot }) => {
  await openWorkspace(page)
  const main = page.getByRole('main')

  await clickRulerAt(page, 20.6)
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(20.6, 0)
  expect((await videoState(page)).paused).toBe(true)
  await expect(page.getByTestId('now-strip')).toContainText('Pour and first sip')
  await expect(page.getByTestId('now-strip')).toContainText('Now it feels like home')
  await expect(page).toHaveURL(/[?&]t=20\.\d/)

  // Playhead sits where the click was.
  const ruler = await box(page.getByTestId('timeline-ruler'))
  const head = await box(page.getByTestId('timeline-playhead'))
  expect(Math.abs(head.x - (ruler.x + (20.6 / DURATION) * ruler.width))).toBeLessThan(3)
  await shot('scene-workspace-seek-20s')

  // Play, then seek again: playback continues from the new time and the page does not scroll.
  await page.getByTestId('player-play').click()
  await expect.poll(() => videoState(page).then((v) => v.paused)).toBe(false)
  const scrollBefore = await main.evaluate((node) => node.scrollTop)
  await page.locator('[data-lane="segments"]').evaluate((lanes) => {
    const win = window as unknown as { __laneMutations: number }
    win.__laneMutations = 0
    new MutationObserver((records) => (win.__laneMutations += records.length)).observe(lanes.parentElement as Node, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    })
  })
  await clickRulerAt(page, 30)
  await page.waitForTimeout(1200)
  const after = await videoState(page)
  expect(after.paused).toBe(false)
  expect(after.currentTime).toBeGreaterThan(30.5)
  expect(await main.evaluate((node) => node.scrollTop)).toBe(scrollBefore)
  // The only lane DOM change in over a second of playback is the ruler's once-per-second aria value.
  const mutations = await page.evaluate(() => (window as unknown as { __laneMutations: number }).__laneMutations)
  expect(mutations).toBeLessThanOrEqual(6)
  await page.getByTestId('player-play').click()
})

test('wheel zooms about the cursor, drag pans, buttons and minimap set the range', async ({ page, shot }) => {
  await openWorkspace(page)
  const lane = await box(page.locator('[data-lane="segments"] > div:nth-child(2)'))
  const anchorX = lane.x + lane.width * 0.25
  const anchorTime = DURATION * 0.25

  await page.mouse.move(anchorX, lane.y + lane.height / 2)
  await page.mouse.wheel(0, -600)
  await expect.poll(() => visibleRange(page).then((r) => r.end - r.start)).toBeLessThan(20)
  const zoomed = await visibleRange(page)
  // The time under the cursor is still a quarter of the way across the view.
  expect((anchorTime - zoomed.start) / (zoomed.end - zoomed.start)).toBeCloseTo(0.25, 1)
  await shot('scene-workspace-zoomed')

  // Drag the plot to the left: the view moves later in time, same span.
  await page.mouse.move(lane.x + lane.width * 0.6, lane.y + lane.height / 2)
  await page.mouse.down()
  await page.mouse.move(lane.x + lane.width * 0.3, lane.y + lane.height / 2, { steps: 8 })
  await page.mouse.up()
  const panned = await visibleRange(page)
  expect(panned.start).toBeGreaterThan(zoomed.start + 1)
  expect(panned.end - panned.start).toBeCloseTo(zoomed.end - zoomed.start, 0)

  // Minimap brush shows the range; dragging it back to the left edge pans to the start.
  // The minimap sits below the fold at this viewport height; the mouse only reaches what is on screen.
  await page.getByTestId('minimap-track').scrollIntoViewIfNeeded()
  const brush = await box(page.getByTestId('minimap-brush'))
  const track = await box(page.getByTestId('minimap-track'))
  expect((brush.x - track.x) / track.width).toBeCloseTo(panned.start / DURATION, 1)
  await page.mouse.move(brush.x + brush.width / 2, brush.y + brush.height / 2)
  await page.mouse.down()
  await page.mouse.move(track.x, brush.y + brush.height / 2, { steps: 6 })
  await page.mouse.up()
  expect((await visibleRange(page)).start).toBe(0)

  await page.getByRole('button', { name: 'Zoom in' }).click()
  expect((await visibleRange(page)).end).toBeLessThan(panned.end - panned.start)
  await page.getByRole('button', { name: 'Fit whole video' }).click()
  expect(await visibleRange(page)).toEqual({ start: 0, end: DURATION })
  await expect(page.getByRole('button', { name: 'Zoom out' })).toBeDisabled()
})

test('tabs, transcript search and click-to-seek, entity pinning, lane toggles', async ({ page, shot }) => {
  await openWorkspace(page)

  await page.getByRole('tab', { name: /Transcript/ }).click()
  const transcript = page.getByTestId('transcript-list')
  const panel = page.getByRole('tabpanel', { name: /Transcript/ })
  // The list is windowed: all 20 cues are counted, only the rows near the scroll position are mounted,
  // and the rest come into the DOM as the list scrolls.
  await expect(panel.getByText('20 of 20')).toBeVisible()
  const mounted = await transcript.getByRole('listitem').count()
  expect(mounted).toBeGreaterThan(0)
  expect(mounted).toBeLessThan(20)
  await expect(transcript.getByText('Offer ends 31 August', { exact: false })).toHaveCount(0)
  await transcript.evaluate((node) => node.scrollTo(0, node.scrollHeight))
  await expect(transcript.getByText('Offer ends 31 August', { exact: false })).toBeVisible()
  await page.getByTestId('panel-search').fill('kadak')
  await expect(panel.getByText('3 of 20')).toBeVisible()
  await expect(transcript.getByRole('listitem')).toHaveCount(3)
  await expect(transcript.locator('mark').first()).toHaveText(/kadak/i)
  await transcript.getByText('Made strong, for the days that need it.', { exact: false }).click()
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(34.2, 1)
  await expect(page.getByTestId('timeline-selection')).toBeVisible()
  await shot('scene-workspace-transcript-search')

  // The shared search carries over to the Entities tab.
  await page.getByRole('tab', { name: /Entities/ }).click()
  await expect(page.getByTestId('entity-list').getByRole('listitem')).toHaveCount(1)
  await page.getByTestId('panel-search').fill('')
  await expect(page.getByTestId('entity-list').getByRole('listitem')).toHaveCount(9)
  await expect(page.locator('[data-lane="entity:ent-2"]')).toHaveCount(0)
  await page.getByTestId('pin-ent-2').click()
  await expect(page.locator('[data-lane="entity:ent-2"]')).toBeVisible()
  await expect(page.locator('[data-lane="entity:ent-2"] [data-tl-item]')).toHaveCount(3)
  await shot('scene-workspace-entities-pinned')

  await page.getByRole('button', { name: 'Show or hide lanes' }).click()
  await page.getByRole('menuitemcheckbox', { name: 'Filmstrip' }).click()
  await expect(page.locator('[data-lane="filmstrip"]')).toHaveCount(0)
  await page.keyboard.press('Escape')

  // The same moment is also a marker on the timeline, so look inside the tab panel.
  await page.getByRole('tab', { name: /Moments/ }).click()
  // The list starts right under a normal-height search box (no stretched gap above it).
  const search = await box(page.getByTestId('panel-search'))
  const firstRow = await box(page.getByRole('tabpanel', { name: /Moments/ }).getByRole('button').first())
  expect(search.height).toBeLessThan(40)
  expect(firstRow.y - (search.y + search.height)).toBeLessThan(60)
  await page.getByRole('tabpanel', { name: /Moments/ }).getByRole('button', { name: /Stronger than the knees/ }).click()
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(30.9, 1)
  await expect(page.locator('[data-lane="moments"] [data-tl-item][aria-pressed="true"]')).toHaveCount(1)
  await page.getByRole('tab', { name: /Events/ }).click()
  await expect(page.getByRole('tabpanel', { name: /Events/ }).getByRole('button', { name: /Hero shot of the pack/ })).toBeVisible()
  await page.getByRole('tab', { name: /Objects & Ads/ }).click()
  const objectsAdsPanel = page.getByRole('tabpanel', { name: /Objects & Ads/ })
  await expect(objectsAdsPanel.getByRole('button', { name: /Kitchen appliances & cookware/ })).toBeVisible()
  await expect(objectsAdsPanel.getByText('Kadak Chai pack', { exact: true })).toBeVisible()
})

test('keyboard shortcuts, lane keyboard access and hover card', async ({ page, shot }) => {
  await openWorkspace(page)
  await page.getByTestId('now-strip').click()

  await page.keyboard.press(']')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(3.2, 1)
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(8.2, 1)
  await page.keyboard.press('l')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(18.2, 1)
  // 18.2 s is 0.8 s into segment 5 (17.4 s): `[` restarts it. Pressed again at its start, it goes one back.
  await page.keyboard.press('[')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(17.4, 1)
  await page.keyboard.press('[')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(12, 1)
  await page.keyboard.press('j')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(2, 1)
  await page.keyboard.press(' ')
  await expect.poll(() => videoState(page).then((v) => v.paused)).toBe(false)
  await page.keyboard.press('k')
  await expect.poll(() => videoState(page).then((v) => v.paused)).toBe(true)

  // A lane is one tab stop; arrows move between its items and Enter activates.
  const firstSegment = page.locator('[data-lane="segments"] [data-tl-item]').first()
  await firstSegment.focus()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expect(page.locator('[data-lane="segments"] [data-tl-item]').nth(2)).toBeFocused()
  await page.keyboard.press('Enter')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(7.5, 1)
  await expect(page.locator('[data-lane="segments"] [data-tl-item]').nth(2)).toHaveAttribute('aria-pressed', 'true')
  await shot('scene-workspace-keyboard-focus')

  await page.locator('[data-lane="emotions"]').scrollIntoViewIfNeeded()
  const lane = await box(page.locator('[data-lane="emotions"] > div:nth-child(2)'))
  await page.mouse.move(lane.x + (30 / DURATION) * lane.width, lane.y + lane.height / 2)
  const card = page.getByTestId('timeline-hover-card')
  await expect(card).toContainText('Shared laughter on the balcony')
  await expect(card).toContainText('Mr. Rao')
  await expect(card).toContainText('Humor 80%')
  await shot('scene-workspace-hover-card')
})

test('a link with ?t= and ?sel= reopens at the same moment with the item selected', async ({ page, shot }) => {
  await openWorkspace(page, '?t=20.6&sel=seg-5')
  await expect.poll(() => videoState(page).then((v) => v.currentTime)).toBeCloseTo(20.6, 1)
  await expect(page.getByTestId('player-time')).toContainText('0:20.6')
  await expect(page.locator('[data-lane="segments"] [data-tl-item][aria-pressed="true"]')).toHaveCount(1)
  await expect(page.getByTestId('timeline-selection')).toBeVisible()
  await shot('scene-workspace-deep-link')

  // Looping the selected segment wraps playback back to its start.
  await page.getByTestId('player-loop').click()
  await clickRulerAt(page, 22.4)
  await page.getByTestId('player-rate').selectOption('2')
  await page.getByTestId('player-play').click()
  await expect.poll(() => videoState(page).then((v) => v.currentTime), { timeout: 8000 }).toBeLessThan(19)
  expect((await videoState(page)).currentTime).toBeGreaterThanOrEqual(17.3)
  expect((await videoState(page)).playbackRate).toBe(2)
  await page.getByTestId('player-play').click()
})

test('export menu downloads subtitles and CSV generated in the browser', async ({ page }) => {
  await openWorkspace(page)

  await page.getByTestId('export-menu').click()
  const [srt] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: 'SubRip (.srt)' }).click()])
  expect(srt.suggestedFilename()).toBe('kadak-chai-monsoon-45s.srt')
  const srtText = await (await srt.createReadStream()).toArray().then((chunks) => Buffer.concat(chunks).toString('utf8'))
  expect(srtText.startsWith('1\n00:00:00,000 --> 00:00:03,200\n[Heavy rain and distant thunder]\n')).toBe(true)

  await page.getByTestId('export-menu').click()
  const [csv] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: /Key moments/ }).click()])
  expect(csv.suggestedFilename()).toBe('kadak-chai-monsoon-45s-key_moments.csv')
  const csvText = await (await csv.createReadStream()).toArray().then((chunks) => Buffer.concat(chunks).toString('utf8'))
  expect(csvText.split('\r\n')[0]).toBe('id,start_sec,type,label')
  expect(csvText.split('\r\n')).toHaveLength(11)
})

test('a running job shows the stage stepper and opens the workspace when it completes', async ({ page, stub, shot }) => {
  await stub.advanceSceneAnalysis('sa-fixture-running', 3)
  await page.goto('/scene-analysis/sa-fixture-running')
  const progress = page.getByTestId('processing-view')
  await expect(progress).toBeVisible({ timeout: 60_000 })
  await expect(progress.locator('li[data-state="active"]')).toContainText('Analysing')
  await expect(progress.locator('li[data-state="done"]')).toHaveCount(1)
  await expect(progress).toContainText(/window \d of 3/)
  await shot('scene-workspace-processing')

  await stub.advanceSceneAnalysis('sa-fixture-running', 7)
  await expect(page.getByTestId('timeline-ruler')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('processing-view')).toHaveCount(0)
})

test('a failed job shows the error and retry restarts it', async ({ page, shot }) => {
  await page.goto('/scene-analysis/sa-fixture-failed')
  const progress = page.getByTestId('processing-view')
  await expect(progress.getByRole('alert')).toBeVisible({ timeout: 60_000 })
  await expect(progress.locator('li[data-state="failed"]')).toContainText('Analysing')
  await shot('scene-workspace-failed')

  await progress.getByRole('button', { name: 'Retry analysis' }).click()
  await expect(progress.getByRole('alert')).toHaveCount(0)
  await expect(progress.getByRole('status')).toBeVisible()
})

test('light theme and a narrow window keep the workspace readable', async ({ page, shot }) => {
  await page.addInitScript(() => window.localStorage.setItem('theme', 'light'))
  await openWorkspace(page)
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByRole('tab', { name: /Moments/ }).click()
  await shot('scene-workspace-light')

  await page.setViewportSize({ width: 900, height: 900 })
  await expect(page.getByTestId('timeline-ruler')).toBeVisible()
  const plots = await page.locator('[data-lane] > div:nth-child(2)').evaluateAll((nodes) =>
    nodes.map((node) => Math.round(node.getBoundingClientRect().width)),
  )
  expect(new Set(plots).size).toBe(1)
  expect(plots[0]).toBeGreaterThan(300)
  await shot('scene-workspace-narrow')
})
