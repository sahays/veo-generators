/**
 * Viewport maths for the shared timeline. A viewport is the visible time
 * range in seconds; a scale maps it onto the plot width in pixels. Every lane
 * uses the one scale built here, which is what keeps lanes aligned.
 */

export interface Viewport {
  start: number
  end: number
}

export interface TimeScale {
  readonly view: Viewport
  readonly width: number
  readonly pxPerSec: number
  toX: (timeSec: number) => number
  toTime: (xPx: number) => number
}

/** Smallest span the user can zoom into, in seconds. */
export const MIN_SPAN_SEC = 1

export function minSpanFor(duration: number): number {
  return Math.min(MIN_SPAN_SEC, Math.max(duration, 0))
}

export function clampTime(t: number, duration: number): number {
  if (!Number.isFinite(t)) return 0
  return Math.min(Math.max(t, 0), Math.max(duration, 0))
}

export function fitViewport(duration: number): Viewport {
  return { start: 0, end: Math.max(duration, 0) }
}

/**
 * Force a viewport inside `[0, duration]` with a span of at least the minimum.
 * The span is preserved where possible: a range pushed past an edge slides
 * back instead of shrinking.
 */
export function clampViewport(view: Viewport, duration: number): Viewport {
  const total = Math.max(duration, 0)
  const lo = Math.min(view.start, view.end)
  const hi = Math.max(view.start, view.end)
  const rawSpan = Number.isFinite(hi - lo) ? hi - lo : total
  const span = Math.min(Math.max(rawSpan, minSpanFor(total)), total)
  const start = Math.min(Math.max(Number.isFinite(lo) ? lo : 0, 0), total - span)
  return { start, end: start + span }
}

/**
 * Zoom by `factor` (> 1 zooms in) keeping `anchorSec` at the same fraction of
 * the viewport, i.e. the time under the cursor stays under the cursor.
 */
export function zoomViewport(view: Viewport, factor: number, anchorSec: number, duration: number): Viewport {
  const span = view.end - view.start
  if (!(factor > 0) || span <= 0) return clampViewport(view, duration)
  const anchor = Math.min(Math.max(anchorSec, view.start), view.end)
  const ratio = (anchor - view.start) / span
  const nextSpan = Math.min(Math.max(span / factor, minSpanFor(duration)), Math.max(duration, 0))
  const start = anchor - ratio * nextSpan
  return clampViewport({ start, end: start + nextSpan }, duration)
}

export function panViewport(view: Viewport, deltaSec: number, duration: number): Viewport {
  return clampViewport({ start: view.start + deltaSec, end: view.end + deltaSec }, duration)
}

/** Viewport showing `range` with `padRatio` of its length added on each side. */
export function viewportForRange(range: Viewport, duration: number, padRatio = 0.15): Viewport {
  const pad = Math.max(range.end - range.start, 0) * padRatio
  return clampViewport({ start: range.start - pad, end: range.end + pad }, duration)
}

/**
 * Page the viewport so `timeSec` is visible, keeping the span. Returns the
 * same object when the time is already in view so callers can skip updates.
 */
export function revealTime(view: Viewport, timeSec: number, duration: number, leadRatio = 0.1): Viewport {
  if (timeSec >= view.start && timeSec <= view.end) return view
  const span = view.end - view.start
  const start = timeSec - span * leadRatio
  return clampViewport({ start, end: start + span }, duration)
}

export function createTimeScale(view: Viewport, width: number): TimeScale {
  const span = Math.max(view.end - view.start, Number.EPSILON)
  const safeWidth = Math.max(width, 0)
  const pxPerSec = safeWidth / span
  return {
    view,
    width: safeWidth,
    pxPerSec,
    toX: (timeSec) => (timeSec - view.start) * pxPerSec,
    toTime: (xPx) => (pxPerSec > 0 ? view.start + xPx / pxPerSec : view.start),
  }
}

/** True when the viewport shows the whole duration. */
export function isFitted(view: Viewport, duration: number): boolean {
  return view.start <= 1e-6 && view.end >= duration - 1e-6
}
