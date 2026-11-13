import type { TimeRange } from '@/types/insights'
import { partitionPoint } from './bisect'
import type { Viewport } from './viewport'

/** `[time_sec, value]`, sorted by time. Matches `SignalPoint` in the contract. */
export type SeriesPoint = readonly [number, number]

/**
 * Points inside the viewport plus one neighbour on each side, so a line drawn
 * through the result enters and leaves the plot instead of stopping short.
 */
export function sliceVisible(points: readonly SeriesPoint[], view: Viewport): SeriesPoint[] {
  const first = partitionPoint(points.length, (i) => points[i][0] < view.start)
  const last = partitionPoint(points.length, (i) => points[i][0] <= view.end)
  return points.slice(Math.max(first - 1, 0), Math.min(last + 1, points.length))
}

/** Push the lowest and highest point of one bucket, in time order. */
function pushBucketExtremes(out: SeriesPoint[], points: readonly SeriesPoint[], from: number, to: number): void {
  let lo = from
  let hi = from
  for (let i = from + 1; i < to; i++) {
    if (points[i][1] < points[lo][1]) lo = i
    if (points[i][1] > points[hi][1]) hi = i
  }
  out.push(points[Math.min(lo, hi)])
  if (lo !== hi) out.push(points[Math.max(lo, hi)])
}

/**
 * Reduce a series to at most `maxPoints` while keeping every peak and trough
 * visible: each bucket contributes its minimum and its maximum.
 */
export function downsampleMinMax(points: readonly SeriesPoint[], maxPoints: number): SeriesPoint[] {
  const budget = Math.max(Math.floor(maxPoints), 2)
  if (points.length <= budget) return [...points]
  const buckets = Math.max(Math.floor(budget / 2), 1)
  const size = points.length / buckets
  const out: SeriesPoint[] = []
  for (let b = 0; b < buckets; b++) {
    const from = Math.floor(b * size)
    const to = Math.min(Math.max(Math.floor((b + 1) * size), from + 1), points.length)
    pushBucketExtremes(out, points, from, to)
  }
  return out
}

/** Visible slice of a series reduced to about one point per pixel of plot width. */
export function downsampleForView(points: readonly SeriesPoint[], view: Viewport, widthPx: number): SeriesPoint[] {
  return downsampleMinMax(sliceVisible(points, view), Math.max(Math.floor(widthPx), 2))
}

/**
 * Share of each of `binCount` equal bins across the viewport that is covered
 * by the given ranges, 0..1. `ranges` should already be limited to the ones
 * overlapping the viewport (see `IntervalIndex.overlapping`); each range only
 * touches the bins it spans.
 */
export function coverageBins(ranges: readonly TimeRange[], view: Viewport, binCount: number): number[] {
  const bins = new Array<number>(Math.max(Math.floor(binCount), 0)).fill(0)
  const binSec = (view.end - view.start) / bins.length
  if (!(binSec > 0)) return bins
  for (const range of ranges) {
    const from = Math.max(range.start_sec, view.start)
    const to = Math.min(range.end_sec, view.end)
    const lastBin = Math.min(Math.ceil((to - view.start) / binSec), bins.length)
    for (let b = Math.max(Math.floor((from - view.start) / binSec), 0); b < lastBin; b++) {
      const binStart = view.start + b * binSec
      const overlap = Math.min(to, binStart + binSec) - Math.max(from, binStart)
      if (overlap > 0) bins[b] = Math.min(bins[b] + overlap / binSec, 1)
    }
  }
  return bins
}
