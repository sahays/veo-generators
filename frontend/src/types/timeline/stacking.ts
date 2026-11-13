import type { TimeRange } from '@/types/insights'
import { IntervalIndex } from './intervalIndex'

/**
 * Collision stacking for timeline markers. Markers are placed left to right
 * into the first row where they fit; when every row is taken, the marker is
 * folded into the nearest placed marker, which then renders as a count badge.
 * Two placed markers in one row therefore never overlap, at any zoom level,
 * and the lane height stays fixed.
 */

export interface PixelSpan {
  x0: number
  x1: number
}

export interface PlacedMarker<T> extends PixelSpan {
  row: number
  /** The marker's own item first, then any items folded into it. */
  items: T[]
}

export interface StackOptions {
  /** Minimum horizontal gap between two markers in a row, in pixels. */
  gap: number
  /** Rows available in the lane. */
  maxRows: number
}

/** Row whose last marker ends furthest left, i.e. the first one to free up. */
function earliestRow(rowEnds: readonly number[]): number {
  let best = 0
  for (let row = 1; row < rowEnds.length; row++) {
    if (rowEnds[row] < rowEnds[best]) best = row
  }
  return best
}

/**
 * Assign rows to markers. `extent` gives a marker's pixel span. Rows are
 * capped at `maxRows`, so each placement inspects a constant number of rows
 * and the pass is linear after the sort.
 */
export function stackMarkers<T>(
  items: readonly T[],
  extent: (item: T) => PixelSpan,
  options: StackOptions,
): PlacedMarker<T>[] {
  const maxRows = Math.max(Math.floor(options.maxRows), 1)
  const spans = items.map((item) => ({ item, span: extent(item) })).sort((a, b) => a.span.x0 - b.span.x0)
  const placed: PlacedMarker<T>[] = []
  const rowEnds: number[] = []
  const rowLast: PlacedMarker<T>[] = []
  for (const { item, span } of spans) {
    let row = rowEnds.findIndex((end) => end + options.gap <= span.x0)
    if (row < 0 && rowEnds.length < maxRows) row = rowEnds.length
    if (row < 0) {
      const target = rowLast[earliestRow(rowEnds)]
      target.items.push(item)
      target.x1 = Math.max(target.x1, span.x1)
      rowEnds[target.row] = target.x1
      continue
    }
    const marker: PlacedMarker<T> = { x0: span.x0, x1: span.x1, row, items: [item] }
    placed.push(marker)
    rowEnds[row] = span.x1
    rowLast[row] = marker
  }
  return placed
}

/** A placed marker expressed in time, so lanes can query "what is visible" through an index. */
export interface StackedSpan<T> extends TimeRange {
  row: number
  /** The marker's own item first, then any items folded into it. */
  items: T[]
}

function toTimeIndex<T>(placed: readonly PlacedMarker<T>[], secPerUnit: number): IntervalIndex<StackedSpan<T>> {
  return new IntervalIndex(
    placed.map((p) => ({ start_sec: p.x0 * secPerUnit, end_sec: p.x1 * secPerUnit, row: p.row, items: p.items })),
  )
}

/**
 * Rows for ranges that may overlap in time (emotions, beats). The result does
 * not depend on zoom, so it is computed once per document.
 */
export function stackRanges<T extends TimeRange>(items: readonly T[], maxRows: number): IntervalIndex<StackedSpan<T>> {
  const placed = stackMarkers(items, (item) => ({ x0: item.start_sec, x1: item.end_sec }), { gap: 0, maxRows })
  return toTimeIndex(placed, 1)
}

/**
 * Rows for fixed-size glyphs at a given zoom. Stacking is done for the whole
 * lane in absolute pixels, so markers keep their row while the view pans;
 * only a zoom change can move them.
 */
export function stackPoints<T extends { start_sec: number }>(
  items: readonly T[],
  pxPerSec: number,
  glyphPx: number,
  options: StackOptions,
): IntervalIndex<StackedSpan<T>> {
  if (!(pxPerSec > 0)) return new IntervalIndex<StackedSpan<T>>([])
  const half = glyphPx / 2
  const extent = (item: T): PixelSpan => ({ x0: item.start_sec * pxPerSec - half, x1: item.start_sec * pxPerSec + half })
  return toTimeIndex(stackMarkers(items, extent, options), 1 / pxPerSec)
}
