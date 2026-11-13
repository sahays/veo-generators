import { lowerBound, upperBound } from './bisect'

/**
 * Windowed rendering for long lists without a virtualisation library.
 * Rows keep their natural height in normal document flow; only the rows near
 * the scroll position are mounted, and two spacers stand in for the rest.
 * Heights are estimates, so a wrong guess shifts the scroll thumb slightly
 * but can never make rows overlap.
 */

export interface ListWindow {
  /** First mounted row. */
  start: number
  /** One past the last mounted row. */
  end: number
  /** Height of the spacer before the mounted rows, in pixels. */
  padTop: number
  /** Height of the spacer after the mounted rows, in pixels. */
  padBottom: number
}

/** `offsets[i]` is the top of row `i`; `offsets[n]` is the total height. */
export function prefixOffsets(heights: readonly number[]): Float64Array {
  const offsets = new Float64Array(heights.length + 1)
  heights.forEach((height, i) => {
    offsets[i + 1] = offsets[i] + Math.max(height, 0)
  })
  return offsets
}

/** Estimated height of a text row that wraps at `charsPerLine`. */
export function estimateRowHeight(textLength: number, charsPerLine: number, lineHeight: number, chrome: number): number {
  const lines = Math.max(Math.ceil(textLength / Math.max(charsPerLine, 1)), 1)
  return chrome + lines * lineHeight
}

/** Rows intersecting `[scrollTop - overscan, scrollTop + viewport + overscan]`. */
export function computeWindow(
  offsets: Float64Array,
  scrollTop: number,
  viewportHeight: number,
  overscan: number,
): ListWindow {
  const count = offsets.length - 1
  const total = offsets[count] ?? 0
  const top = Math.min(Math.max(scrollTop - overscan, 0), total)
  const bottom = Math.min(Math.max(scrollTop + viewportHeight + overscan, 0), total)
  const start = Math.min(Math.max(upperBound(offsets, top) - 1, 0), count)
  const end = Math.min(Math.max(lowerBound(offsets, bottom), start), count)
  return { start, end, padTop: offsets[start] ?? 0, padBottom: total - (offsets[end] ?? total) }
}

/**
 * Scroll position that brings row `index` into view, or null when it already
 * is. Used to follow the playhead inside the list's own scroll container,
 * which never scrolls the page.
 */
export function scrollTopToReveal(
  offsets: Float64Array,
  index: number,
  scrollTop: number,
  viewportHeight: number,
): number | null {
  const rowTop = offsets[index]
  const rowBottom = offsets[index + 1]
  if (rowTop === undefined || rowBottom === undefined) return null
  if (rowTop >= scrollTop && rowBottom <= scrollTop + viewportHeight) return null
  return Math.max(rowTop - viewportHeight / 3, 0)
}
