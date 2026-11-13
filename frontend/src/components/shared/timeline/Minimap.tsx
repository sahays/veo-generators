import { useEffect, useMemo, useRef } from 'react'
import { useTimelineKit, useTimelineView } from '@/hooks/timeline/timelineContext'
import { useElementSize } from '@/hooks/timeline/useElementSize'
import type { ViewportApi } from '@/hooks/timeline/useTimelineViewport'
import { cn } from '@/lib/utils'
import type { TimeRange } from '@/types/insights'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { createTimeScale, fitViewport, minSpanFor, type TimeScale, type Viewport } from '@/types/timeline/viewport'
import { LANE_HEIGHT, TIMELINE_GUTTER_PX } from './layout'

const HEIGHT = LANE_HEIGHT.minimap
const MIN_BRUSH_PX = 10
const KEY_PAN_RATIO = 0.1
const KEY_ZOOM_FACTOR = 1.5

type BrushMode = 'move' | 'start' | 'end'

interface BrushDrag {
  mode: BrushMode
  startX: number
  startView: Viewport
}

/** Viewport after dragging the brush (or one of its edges) by `deltaSec`. */
function draggedView(drag: BrushDrag, deltaSec: number, duration: number): Viewport {
  const { start, end } = drag.startView
  const minSpan = minSpanFor(duration)
  if (drag.mode === 'start') return { start: Math.min(Math.max(start + deltaSec, 0), end - minSpan), end }
  if (drag.mode === 'end') return { start, end: Math.max(Math.min(end + deltaSec, duration), start + minSpan) }
  return { start: start + deltaSec, end: end + deltaSec }
}

type BrushHandlers = (mode: BrushMode) => React.DOMAttributes<HTMLDivElement>

/** Pointer handlers for moving the brush and resizing it from either edge. */
function useBrushDrag(scale: TimeScale): BrushHandlers {
  const { viewport, duration } = useTimelineKit()
  const drag = useRef<BrushDrag | null>(null)
  const end = (): void => {
    drag.current = null
  }
  return (mode) => ({
    onPointerDown: (event) => {
      if (event.button !== 0) return
      event.stopPropagation()
      event.currentTarget.setPointerCapture(event.pointerId)
      drag.current = { mode, startX: event.clientX, startView: viewport.getView() }
    },
    onPointerMove: (event) => {
      if (!drag.current || scale.pxPerSec <= 0) return
      viewport.setView(draggedView(drag.current, (event.clientX - drag.current.startX) / scale.pxPerSec, duration))
    },
    onPointerUp: end,
    onPointerCancel: end,
  })
}

function brushKeyAction(event: React.KeyboardEvent<HTMLDivElement>, viewport: ViewportApi): boolean {
  const view = viewport.getView()
  const step = (view.end - view.start) * KEY_PAN_RATIO
  if (event.key === 'ArrowLeft') viewport.panBy(-step)
  else if (event.key === 'ArrowRight') viewport.panBy(step)
  else if (event.key === 'ArrowUp' || event.key === '+' || event.key === '=') viewport.zoomBy(KEY_ZOOM_FACTOR)
  else if (event.key === 'ArrowDown' || event.key === '-') viewport.zoomBy(1 / KEY_ZOOM_FACTOR)
  else if (event.key === 'Home' || event.key === '0') viewport.fit()
  else return false
  return true
}

function BrushHandle({ side, handlers }: { side: 'start' | 'end'; handlers: BrushHandlers }): JSX.Element {
  return (
    <div
      aria-hidden
      data-testid={`minimap-handle-${side}`}
      className={cn('absolute inset-y-0 w-2 cursor-ew-resize touch-none bg-accent/70 hover:bg-accent', side === 'start' ? 'left-0 rounded-l' : 'right-0 rounded-r')}
      {...handlers(side)}
    />
  )
}

/** The draggable, resizable window showing which part of the video the lanes display. */
function Brush({ scale }: { scale: TimeScale }): JSX.Element {
  const { viewport } = useTimelineKit()
  const view = useTimelineView()
  const handlers = useBrushDrag(scale)
  const left = scale.toX(view.start)
  const width = Math.max(scale.toX(view.end) - left, MIN_BRUSH_PX)
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (brushKeyAction(event, viewport)) event.preventDefault()
  }
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label="Visible range. Arrow left and right pan, up and down zoom, Home fits the whole video"
      aria-orientation="horizontal"
      aria-valuemin={0}
      aria-valuemax={Math.round(scale.view.end)}
      aria-valuenow={Math.round(view.start)}
      aria-valuetext={`${formatTimecode(view.start)} to ${formatTimecode(view.end)}`}
      data-testid="minimap-brush"
      className="tl-focusable absolute inset-y-0 cursor-grab touch-none rounded border border-accent/70 bg-accent/15 active:cursor-grabbing"
      style={{ left: Math.min(left, Math.max(scale.width - width, 0)), width }}
      onKeyDown={onKeyDown}
      {...handlers('move')}
    >
      <BrushHandle side="start" handlers={handlers} />
      <BrushHandle side="end" handlers={handlers} />
    </div>
  )
}

/** Playhead tick on the minimap, moved by a clock subscription (no React render). */
function MinimapPlayhead({ scale }: { scale: TimeScale }): JSX.Element {
  const { clock } = useTimelineKit()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const place = (): void => {
      if (ref.current) ref.current.style.transform = `translateX(${scale.toX(clock.getTime()).toFixed(1)}px)`
    }
    place()
    return clock.subscribeTime(place)
  }, [clock, scale])
  return <div ref={ref} aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-0.5 bg-accent" />
}

function MinimapBlocks({ scale, ranges }: { scale: TimeScale; ranges: readonly TimeRange[] }): JSX.Element {
  return (
    <svg aria-hidden width={scale.width} height={HEIGHT} className="absolute inset-0">
      {ranges.map((range, i) => (
        <rect key={range.start_sec} x={scale.toX(range.start_sec) + 0.5} y={9} width={Math.max(scale.toX(range.end_sec) - scale.toX(range.start_sec) - 1, 1)} height={HEIGHT - 18} rx={2} fill={i % 2 === 0 ? 'var(--chart-2)' : 'var(--chart-7)'} fillOpacity={0.35} />
      ))}
    </svg>
  )
}

export interface MinimapProps {
  /** Optional overview blocks drawn behind the brush, usually the segments. */
  ranges?: readonly TimeRange[]
  label?: string
  className?: string
}

/**
 * Overview of the whole video with a brush for the visible range. Drag the
 * brush to pan, drag its edges to zoom, click the track to centre the view
 * there. Place it directly under `TimelineSurface`: it uses the same gutter,
 * so its track lines up with the lane plots.
 */
export function Minimap({ ranges = [], label = 'Overview', className }: MinimapProps): JSX.Element {
  const { viewport, duration } = useTimelineKit()
  const [trackRef, size] = useElementSize<HTMLDivElement>()
  const scale = useMemo(() => createTimeScale(fitViewport(duration), size.width), [duration, size.width])
  const centreOn = (event: React.PointerEvent<HTMLDivElement>): void => {
    const view = viewport.getView()
    const half = (view.end - view.start) / 2
    const time = scale.toTime(event.clientX - event.currentTarget.getBoundingClientRect().left)
    viewport.setView({ start: time - half, end: time + half })
  }
  return (
    <div className={cn('flex select-none rounded-lg border border-border bg-card', className)}>
      <div className="flex shrink-0 items-center border-r border-border/60 bg-muted/30 px-2.5 text-[11px] font-medium text-muted-foreground" style={{ width: TIMELINE_GUTTER_PX }}>
        {label}
      </div>
      <div ref={trackRef} data-testid="minimap-track" className="relative min-w-0 flex-1 cursor-pointer overflow-hidden" style={{ height: HEIGHT }} onPointerDown={centreOn}>
        <MinimapBlocks scale={scale} ranges={ranges} />
        <MinimapPlayhead scale={scale} />
        <Brush scale={scale} />
      </div>
    </div>
  )
}
