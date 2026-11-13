import { useEffect, useMemo, useRef, useState } from 'react'
import type { TimeRange } from '@/types/insights'
import {
  clampViewport,
  fitViewport,
  panViewport,
  revealTime,
  viewportForRange,
  zoomViewport,
  type Viewport,
} from '@/types/timeline/viewport'

/** Stable actions on the shared viewport. Safe to call from event handlers and subscriptions. */
export interface ViewportApi {
  getView: () => Viewport
  setView: (view: Viewport) => void
  /** Zoom by `factor` (> 1 zooms in) keeping `anchorSec` fixed on screen. */
  zoomAt: (factor: number, anchorSec: number) => void
  /** Zoom about the centre of the viewport. */
  zoomBy: (factor: number) => void
  panBy: (deltaSec: number) => void
  fit: () => void
  /** Show a time range with a little padding on each side. */
  showRange: (range: TimeRange, padRatio?: number) => void
  /** Page the viewport, if needed, so `timeSec` is visible. */
  reveal: (timeSec: number) => void
}

function sameView(a: Viewport, b: Viewport): boolean {
  return a.start === b.start && a.end === b.end
}

type Update = (prev: Viewport) => Viewport

function buildApi(duration: number, read: () => Viewport, update: (fn: Update) => void): ViewportApi {
  return {
    getView: read,
    setView: (view) => update(() => clampViewport(view, duration)),
    zoomAt: (factor, anchorSec) => update((prev) => zoomViewport(prev, factor, anchorSec, duration)),
    zoomBy: (factor) => update((prev) => zoomViewport(prev, factor, (prev.start + prev.end) / 2, duration)),
    panBy: (deltaSec) => update((prev) => panViewport(prev, deltaSec, duration)),
    fit: () => update(() => fitViewport(duration)),
    showRange: (range, padRatio) =>
      update(() => viewportForRange({ start: range.start_sec, end: range.end_sec }, duration, padRatio)),
    reveal: (timeSec) => update((prev) => revealTime(prev, timeSec, duration)),
  }
}

/**
 * The one visible time range shared by every lane of a timeline. The time
 * domain is `[0, duration]`. `api` keeps its identity for a given duration,
 * so it can be put in context without re-rendering consumers on zoom or pan;
 * only `view` changes.
 */
export function useTimelineViewport(duration: number): { view: Viewport; api: ViewportApi } {
  const [view, setView] = useState<Viewport>(() => fitViewport(duration))
  const latest = useRef(view)
  latest.current = view

  const api = useMemo(() => {
    const update = (fn: Update): void => {
      setView((prev) => {
        const next = fn(prev)
        return sameView(prev, next) ? prev : next
      })
    }
    return buildApi(duration, () => latest.current, update)
  }, [duration])

  useEffect(() => {
    api.fit()
  }, [api])

  return { view, api }
}
