import { useMemo, useState } from 'react'
import { TimeScaleContext, useTimelineKit, useTimelineView } from '@/hooks/timeline/timelineContext'
import { useElementSize } from '@/hooks/timeline/useElementSize'
import { useTimelineGestures } from '@/hooks/timeline/useTimelineGestures'
import type { ViewportApi } from '@/hooks/timeline/useTimelineViewport'
import { cn } from '@/lib/utils'
import { createTimeScale } from '@/types/timeline/viewport'
import { TIMELINE_GUTTER_PX } from './layout'
import { HoverLayer } from './TimelineHover'
import { Playhead, SelectionBand } from './TimelineOverlay'

const KEY_ZOOM_FACTOR = 1.5

function zoomWithKeyboard(event: React.KeyboardEvent<HTMLDivElement>, viewport: ViewportApi): void {
  if (event.ctrlKey || event.metaKey || event.altKey) return
  if (event.key === '+' || event.key === '=') viewport.zoomBy(KEY_ZOOM_FACTOR)
  else if (event.key === '-' || event.key === '_') viewport.zoomBy(1 / KEY_ZOOM_FACTOR)
  else if (event.key === '0') viewport.fit()
}

export interface TimelineSurfaceProps {
  /** Accessible name of the whole timeline, e.g. "Scene timeline". */
  ariaLabel: string
  /** Lanes: kit lanes and/or custom `<TimelineLane>`s, top to bottom. */
  children: React.ReactNode
  /** Content of the card shown next to the hover crosshair. Omit for no hover card. */
  hoverCard?: (timeSec: number) => React.ReactNode
  className?: string
}

/**
 * The multi-lane timeline. Owns the one time-to-pixel scale (from the shared
 * viewport and the measured plot width) and hands it to every lane through
 * context. Wheel zooms about the cursor, Shift+wheel or a horizontal wheel
 * pans, dragging the plot pans, and `+` / `-` / `0` zoom and fit when focus
 * is inside. The playhead, selection band and hover crosshair are drawn in
 * one overlay above the lanes and move without re-rendering them.
 */
export function TimelineSurface({ ariaLabel, children, hoverCard, className }: TimelineSurfaceProps): JSX.Element {
  const { viewport } = useTimelineKit()
  const view = useTimelineView()
  const [plotRef, plotSize, plotNode] = useElementSize<HTMLDivElement>()
  const [lanesNode, setLanesNode] = useState<HTMLDivElement | null>(null)
  const scale = useMemo(() => createTimeScale(view, plotSize.width), [view, plotSize.width])
  const plotLeft = (): number => plotNode?.getBoundingClientRect().left ?? 0
  useTimelineGestures(lanesNode, { scale, api: viewport, plotLeft })

  return (
    <TimeScaleContext.Provider value={scale}>
      <div
        role="group"
        aria-label={ariaLabel}
        onKeyDown={(event) => zoomWithKeyboard(event, viewport)}
        className={cn('relative select-none touch-pan-y rounded-lg border border-border bg-card', className)}
      >
        <div ref={setLanesNode} className="cursor-grab active:cursor-grabbing">
          {children}
        </div>
        <div
          ref={plotRef}
          className="pointer-events-none absolute inset-y-0 right-0 overflow-x-clip"
          style={{ left: TIMELINE_GUTTER_PX }}
        >
          <SelectionBand />
          <Playhead />
          {hoverCard && <HoverLayer target={lanesNode} plot={plotNode} render={hoverCard} />}
        </div>
      </div>
    </TimeScaleContext.Provider>
  )
}
