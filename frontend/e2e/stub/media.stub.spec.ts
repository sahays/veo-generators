/**
 * Proves the browser under test can decode and seek the stub's video over HTTP
 * Range requests, and that a frame identifies its segment by colour. If this
 * fails, player assertions in the page specs cannot be trusted.
 */
import { AD_SPOT_TIMELINE } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { SEGMENT_COLOURS } from './data/palette.ts'
import { expect, test } from './fixtures.ts'

/** H.264 4:2:0 at CRF 23 shifts colours slightly; palette entries differ by far more than this. */
const CHANNEL_TOLERANCE = 28
/** Top-right corner: clear of the burned-in text. The sweep bar only reaches it in the last second. */
const SAMPLE_POINT = { x: 610, y: 14 }

interface FrameProbe {
  currentTime: number
  rgb: [number, number, number]
}

/** Runs in the page: loads the video, seeks, and reads one pixel of the frame shown. */
async function probeFrame(args: { url: string; time: number; x: number; y: number }): Promise<FrameProbe> {
  const video = document.createElement('video')
  video.crossOrigin = 'anonymous'
  video.muted = true
  video.preload = 'auto'
  video.src = args.url
  const once = (name: string) =>
    new Promise<void>((resolve, reject) => {
      video.addEventListener(name, () => resolve(), { once: true })
      video.addEventListener('error', () => reject(new Error(`video error ${video.error?.code}: ${video.error?.message}`)), { once: true })
    })
  await once('loadeddata')
  video.currentTime = args.time
  await once('seeked')
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('2d canvas is unavailable')
  ctx.drawImage(video, 0, 0)
  const [r, g, b] = ctx.getImageData(args.x, args.y, 1, 1).data
  return { currentTime: video.currentTime, rgb: [r, g, b] }
}

function hexToRgb(hex: string): [number, number, number] {
  const value = Number.parseInt(hex, 16)
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff]
}

test('stub video seeks to the requested segment in the browser', async ({ page, stub }) => {
  // Any app page will do; the video is fetched cross-origin from the stub.
  await page.goto('/scene-analysis/new')
  const url = `${stub.origin}/media/ad-spot.mp4`

  // Seek late first, then early, so both directions need a new byte range.
  for (const segmentIndex of [6, 1, 4]) {
    const segment = AD_SPOT_TIMELINE.segments[segmentIndex]
    const time = (segment.start_sec + segment.end_sec) / 2
    const probe = await page.evaluate(probeFrame, { url, time, ...SAMPLE_POINT })
    const expected = hexToRgb(SEGMENT_COLOURS[segmentIndex])

    expect(probe.currentTime).toBeCloseTo(time, 1)
    probe.rgb.forEach((channel, i) => {
      expect(Math.abs(channel - expected[i]), `${segment.id} channel ${i}: got ${probe.rgb}, want ${expected}`).toBeLessThanOrEqual(CHANNEL_TOLERANCE)
    })
  }
})
