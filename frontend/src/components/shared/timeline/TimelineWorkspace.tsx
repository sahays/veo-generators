import { useEffect, useMemo, useState } from 'react'
import {
  TimelineKitContext,
  TimelineViewContext,
  type TimelineKit,
} from '@/hooks/timeline/timelineContext'
import { useMediaClock } from '@/hooks/timeline/useMediaClock'
import { useTimelineViewport } from '@/hooks/timeline/useTimelineViewport'
import { useUrlTimeSync } from '@/hooks/timeline/useUrlTimeSync'
import { createWorkspaceStore, loopRangeOf, type WorkspaceInit } from '@/store/timeline/workspaceStore'
import type { TimelineItemRef } from '@/types/timeline/model'

const NO_ITEMS: ReadonlyMap<string, TimelineItemRef> = new Map()

/** Keep the clock's loop range equal to the selected range while looping is on. */
function useLoopSync(kit: TimelineKit): void {
  useEffect(() => {
    kit.clock.setLoop(loopRangeOf(kit.store.getState()))
    return kit.store.subscribe((state) => kit.clock.setLoop(loopRangeOf(state)))
  }, [kit])
}

/**
 * While playing, page the viewport when the playhead runs off its edge.
 * Only a playhead that was visible is followed, so panning away from it
 * during playback is not undone on the next frame.
 */
function useFollowPlayhead(kit: TimelineKit): void {
  useEffect(() => {
    let last = kit.clock.getTime()
    return kit.clock.subscribeTime(() => {
      const view = kit.viewport.getView()
      const wasVisible = last >= view.start && last <= view.end
      last = kit.clock.getTime()
      if (wasVisible && kit.clock.getState().playing && kit.store.getState().followPlayhead) {
        kit.viewport.reveal(last)
      }
    })
  }, [kit])
}

export interface TimelineWorkspaceProps {
  /** Time domain of the timeline: the video duration in seconds. */
  duration: number
  /** Addressable items, so `?sel=<id>` in a link can be restored (`TimelineModel.itemsById`). */
  items?: ReadonlyMap<string, TimelineItemRef>
  /** Initial pins and hidden lanes for this workspace instance. */
  initial?: WorkspaceInit
  children: React.ReactNode
}

/**
 * Root of a timeline workspace. Creates the media clock, the per-instance
 * workspace store and the shared viewport, wires loop, follow and URL sync,
 * and provides them to `SyncedVideoPlayer`, `TimelineSurface`, the lanes and
 * the panels underneath. Mount one per workspace page.
 */
export function TimelineWorkspace({ duration, items = NO_ITEMS, initial, children }: TimelineWorkspaceProps): JSX.Element {
  const clock = useMediaClock(duration)
  const [store] = useState(() => createWorkspaceStore(initial))
  const { view, api } = useTimelineViewport(duration)
  const kit = useMemo<TimelineKit>(() => ({ clock, store, viewport: api, duration }), [clock, store, api, duration])
  useLoopSync(kit)
  useFollowPlayhead(kit)
  useUrlTimeSync(kit, items)

  return (
    <TimelineKitContext.Provider value={kit}>
      <TimelineViewContext.Provider value={view}>{children}</TimelineViewContext.Provider>
    </TimelineKitContext.Provider>
  )
}
