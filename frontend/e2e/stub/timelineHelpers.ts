/**
 * Page helpers shared by the timeline workspace specs (Scene Analysis and
 * Engagement): the state of the synced video, the visible range, and pointer
 * positions on the shared time scale. The fixture video is 45 s long.
 */
import { expect, type Locator, type Page } from '@playwright/test'

export const DURATION = 45

export interface VideoState {
  currentTime: number
  paused: boolean
  readyState: number
  playbackRate: number
}

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

export function videoState(page: Page): Promise<VideoState> {
  return page.getByTestId('player-video').evaluate((node) => {
    const video = node as HTMLVideoElement
    return { currentTime: video.currentTime, paused: video.paused, readyState: video.readyState, playbackRate: video.playbackRate }
  })
}

/** Waits for a timeline workspace: the ruler is up and the video has metadata. */
export async function expectWorkspaceReady(page: Page): Promise<void> {
  await expect(page.getByTestId('timeline-ruler')).toBeVisible({ timeout: 60_000 })
  await expect.poll(() => videoState(page).then((v) => v.readyState), { timeout: 30_000 }).toBeGreaterThanOrEqual(1)
}

/** Visible range of the timeline in seconds, read from the toolbar read-out. */
export async function visibleRange(page: Page): Promise<{ start: number; end: number }> {
  const text = (await page.getByTestId('timeline-visible-range').innerText()).split('(')[0]
  const [start, end] = text.split('–').map((part) => {
    const [minutes, seconds] = part.trim().split(':')
    return Number(minutes) * 60 + Number(seconds)
  })
  return { start, end }
}

export async function box(locator: Locator): Promise<Box> {
  const rect = await locator.boundingBox()
  if (!rect) throw new Error('element has no bounding box')
  return rect
}

/**
 * `getBoundingClientRect()` of an element. Use this for shapes inside an SVG:
 * Playwright's `boundingBox()` can be a few pixels off for stroked paths.
 */
export function clientRect(locator: Locator): Promise<Box> {
  return locator.evaluate((node) => {
    const rect = node.getBoundingClientRect()
    return { x: rect.left, y: rect.top, width: rect.width, height: rect.height }
  })
}

/** Client x of `timeSec` on a plot that shows the whole video. */
export function xOfTime(plot: Box, timeSec: number): number {
  return plot.x + (timeSec / DURATION) * plot.width
}

/** Click the ruler at `timeSec` assuming the whole video is in view. */
export async function clickRulerAt(page: Page, timeSec: number): Promise<void> {
  const ruler = await box(page.getByTestId('timeline-ruler'))
  await page.mouse.click(xOfTime(ruler, timeSec), ruler.y + ruler.height / 2)
}

/** Drag across `target` from one time to another (whole video in view), optionally holding Shift. */
export async function dragTimes(page: Page, target: Locator, fromSec: number, toSec: number, shift = false): Promise<void> {
  const plot = await box(target)
  const y = plot.y + plot.height / 2
  if (shift) await page.keyboard.down('Shift')
  await page.mouse.move(xOfTime(plot, fromSec), y)
  await page.mouse.down()
  await page.mouse.move(xOfTime(plot, toSec), y, { steps: 8 })
  await page.mouse.up()
  if (shift) await page.keyboard.up('Shift')
}

/** Text of a downloaded file. */
export async function downloadText(download: { createReadStream: () => Promise<NodeJS.ReadableStream> }): Promise<string> {
  const chunks: Buffer[] = []
  for await (const chunk of await download.createReadStream()) chunks.push(Buffer.from(chunk))
  return Buffer.concat(chunks).toString('utf8')
}
