import { useRef } from 'react'
import { clampTime } from '@/types/timeline/viewport'
import { useTimeScale, useTimelineKit } from './timelineContext'

interface ScrubDrag {
  anchorSec: number
  selecting: boolean
}

/**
 * Pointer handlers that scrub the playhead: press or drag seeks to the time
 * under the pointer (any time, not only where there is an item); Shift+drag
 * selects a time range instead. Spread them on an element that spans a lane's
 * plot and give that element the `NO_PAN_ATTR` attribute so the drag does not
 * also pan the timeline. Only valid inside `<TimelineSurface>`.
 */
export function useTimeScrub(): React.DOMAttributes<HTMLDivElement> {
  const { clock, store, duration } = useTimelineKit()
  const scale = useTimeScale()
  const drag = useRef<ScrubDrag | null>(null)
  const timeAt = (event: React.PointerEvent<HTMLDivElement>): number =>
    clampTime(scale.toTime(event.clientX - event.currentTarget.getBoundingClientRect().left), duration)
  const update = (timeSec: number, state: ScrubDrag): void => {
    if (!state.selecting) return clock.seek(timeSec)
    const range = { start_sec: Math.min(state.anchorSec, timeSec), end_sec: Math.max(state.anchorSec, timeSec) }
    store.getState().select({ kind: 'range', id: null, label: 'Selected range', range })
  }
  return {
    onPointerDown: (event) => {
      if (event.button !== 0) return
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { anchorSec: timeAt(event), selecting: event.shiftKey }
      update(drag.current.anchorSec, drag.current)
    },
    onPointerMove: (event) => {
      if (drag.current) update(timeAt(event), drag.current)
    },
    onPointerUp: () => {
      drag.current = null
    },
    onPointerCancel: () => {
      drag.current = null
    },
  }
}
