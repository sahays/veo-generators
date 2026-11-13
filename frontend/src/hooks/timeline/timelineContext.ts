import { createContext, useCallback, useContext } from 'react'
import { useStore } from 'zustand'
import type { MediaClock, SeekOptions } from '@/store/timeline/mediaClock'
import type { TimelineSelection, WorkspaceState, WorkspaceStore } from '@/store/timeline/workspaceStore'
import type { TimeScale, Viewport } from '@/types/timeline/viewport'
import type { ViewportApi } from './useTimelineViewport'

/**
 * Everything a timeline workspace shares that does NOT change during
 * playback, zooming or panning: the clock, the per-workspace store and the
 * viewport actions. Reading this never causes a re-render by itself.
 */
export interface TimelineKit {
  clock: MediaClock
  store: WorkspaceStore
  viewport: ViewportApi
  /** Time domain of the timeline, in seconds. */
  duration: number
}

export const TimelineKitContext = createContext<TimelineKit | null>(null)
/** The visible range. Changes on zoom and pan; only timeline chrome should read it. */
export const TimelineViewContext = createContext<Viewport | null>(null)
/** The time-to-pixel scale of the enclosing `TimelineSurface`. */
export const TimeScaleContext = createContext<TimeScale | null>(null)

function required<T>(value: T | null, what: string): T {
  if (value === null) throw new Error(`${what} is only available inside <TimelineWorkspace>`)
  return value
}

export function useTimelineKit(): TimelineKit {
  return required(useContext(TimelineKitContext), 'useTimelineKit')
}

export function useTimelineView(): Viewport {
  return required(useContext(TimelineViewContext), 'useTimelineView')
}

/** Scale shared by all lanes. Only valid inside `<TimelineSurface>`. */
export function useTimeScale(): TimeScale {
  const scale = useContext(TimeScaleContext)
  if (scale === null) throw new Error('useTimeScale is only available inside <TimelineSurface>')
  return scale
}

/** Subscribe to a slice of the workspace store (selection, pins, lane visibility, search). */
export function useWorkspace<T>(selector: (state: WorkspaceState) => T): T {
  return useStore(useTimelineKit().store, selector)
}

/** Seek and make sure the timeline shows the new time. Playback state is left alone unless asked. */
export function useSeek(): (timeSec: number, options?: SeekOptions) => void {
  const { clock, viewport } = useTimelineKit()
  return useCallback(
    (timeSec, options) => {
      clock.seek(timeSec, options)
      viewport.reveal(timeSec)
    },
    [clock, viewport],
  )
}

/** Select a timeline item and seek to its start: the default click behaviour everywhere. */
export function useSelectItem(): (selection: TimelineSelection) => void {
  const { store } = useTimelineKit()
  const seek = useSeek()
  return useCallback(
    (selection) => {
      store.getState().select(selection)
      seek(selection.range.start_sec)
    },
    [store, seek],
  )
}
