/**
 * Prints the ffmpeg `-filter_complex` graph for the stub's fixture video.
 *
 * The graph is derived from the fixture timeline, so the burned-in segment
 * numbers, titles and boundaries always match what the UI shows for it.
 * Used by `make-media.sh`; not imported by the server.
 *
 *   node e2e/stub/tools/filtergraph.ts <sans-bold.ttf> <mono-bold.ttf>
 *   node e2e/stub/tools/filtergraph.ts            # no fonts: colours and playhead bar only
 */
import { AD_SPOT_TIMELINE } from '../../../src/types/timeline/__tests__/adSpotFixture.ts'
import { SEGMENT_COLOURS } from '../data/palette.ts'

interface SegmentSpec {
  index: number
  start: number
  end: number
  title: string
}

interface Fonts {
  sans: string
  mono: string
}

const WIDTH = 640
const HEIGHT = 360
const FPS = 25

/** Keeps only characters that need no escaping inside a quoted drawtext value. */
function safeText(value: string): string {
  return value.replace(/[^A-Za-z0-9 .\-]/g, '').trim()
}

function assertFontPath(path: string): string {
  if (!/^[A-Za-z0-9_./\-]+$/.test(path)) {
    throw new Error(`Unsupported characters in font path: ${path}`)
  }
  return path
}

function during(seg: SegmentSpec): string {
  return `enable='gte(t,${seg.start})*lt(t,${seg.end})'`
}

function segmentText(seg: SegmentSpec, total: number, fonts: Fonts): string[] {
  const base = `drawtext=fontfile=${fonts.sans}:fontcolor=white`
  const range = `${seg.start.toFixed(2)}s - ${seg.end.toFixed(2)}s`
  return [
    `${base}:text='SEG ${seg.index} of ${total}':fontsize=64:x=32:y=36:${during(seg)}`,
    `${base}:text='${safeText(seg.title)}':fontsize=30:x=32:y=120:${during(seg)}`,
    `${base}@0.8:text='${range}':fontsize=22:x=32:y=166:${during(seg)}`,
  ]
}

function segmentFilters(seg: SegmentSpec, total: number, fonts: Fonts | null): string[] {
  const colour = `0x${SEGMENT_COLOURS[(seg.index - 1) % SEGMENT_COLOURS.length]}`
  const fill = `drawbox=x=0:y=0:w=iw:h=ih:color=${colour}:t=fill:${during(seg)}`
  return fonts ? [fill, ...segmentText(seg, total, fonts)] : [fill]
}

function timecodeFilter(fonts: Fonts): string {
  return (
    `drawtext=fontfile=${fonts.mono}:text='%{pts\\:hms}':fontsize=56:fontcolor=white` +
    ':box=1:boxcolor=black@0.55:boxborderw=12:x=(w-text_w)/2:y=h-text_h-40'
  )
}

/** Full graph: coloured segments, optional text, and a bar that sweeps left to right over the duration. */
function buildGraph(segments: SegmentSpec[], duration: number, fonts: Fonts | null): string {
  const chain = segments.flatMap((seg) => segmentFilters(seg, segments.length, fonts))
  if (fonts) chain.push(timecodeFilter(fonts))
  return [
    `color=c=black:s=${WIDTH}x${HEIGHT}:r=${FPS}:d=${duration}[bg]`,
    `color=c=white:s=6x${HEIGHT}:r=${FPS}:d=${duration}[bar]`,
    `[bg]${chain.join(',')}[painted]`,
    `[painted][bar]overlay=x='(W-w)*t/${duration}':y=0:shortest=1,format=yuv420p[v]`,
  ].join(';')
}

function main(): void {
  const [sans, mono] = process.argv.slice(2)
  const fonts: Fonts | null =
    sans && mono ? { sans: assertFontPath(sans), mono: assertFontPath(mono) } : null
  const segments: SegmentSpec[] = AD_SPOT_TIMELINE.segments.map((seg, i) => ({
    index: i + 1,
    start: seg.start_sec,
    end: seg.end_sec,
    title: seg.title,
  }))
  process.stdout.write(`${buildGraph(segments, AD_SPOT_TIMELINE.duration_sec, fonts)}\n`)
}

main()
