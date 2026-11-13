import { useCallback } from 'react'
import { useSelectItem, useTimelineKit } from '@/hooks/timeline/timelineContext'
import { extremumTitle } from '@/types/engagement/reportModel'
import type { ReportExtremum, TimeRange } from '@/types/insights'

/**
 * Go to a peak, valley or drop: select it, seek to it and zoom the timeline
 * to its context window. Playback state is left alone.
 */
export function useFocusExtremum(): (extremum: ReportExtremum) => void {
  const { viewport } = useTimelineKit()
  const select = useSelectItem()
  return useCallback(
    (extremum) => {
      const range = { start_sec: extremum.time_sec, end_sec: extremum.time_sec }
      select({ kind: 'extremum', id: extremum.id, label: extremumTitle(extremum), range })
      viewport.showRange(extremum.window)
    },
    [select, viewport],
  )
}

/** Go to a time range (a segment, a driver's range): seek to its start and zoom the timeline to it. */
export function useShowRange(): (range: TimeRange) => void {
  const { clock, viewport } = useTimelineKit()
  return useCallback(
    (range) => {
      clock.seek(range.start_sec)
      viewport.showRange(range)
    },
    [clock, viewport],
  )
}
