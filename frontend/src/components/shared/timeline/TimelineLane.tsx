import { useTimeScale, useWorkspace } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'
import type { TimeScale } from '@/types/timeline/viewport'
import { TIMELINE_GUTTER_PX } from './layout'

export interface LaneRenderArgs {
  /** The shared scale: `scale.toX(t)` is the x of time `t` inside this lane's plot. */
  scale: TimeScale
  /** Plot width in pixels (same for every lane). */
  width: number
  height: number
}

export interface TimelineLaneProps {
  /** Stable id; also the key used for lane visibility in the workspace store. */
  id: string
  /** Text shown in the label gutter. */
  label: React.ReactNode
  /** Plot height in pixels. */
  height: number
  /** Extra gutter content after the label, e.g. an unpin button. */
  labelExtra?: React.ReactNode
  className?: string
  /**
   * Plot content. Either nodes, or a function of the scale for content that
   * needs it. The plot box is `position: relative`, exactly `width` x
   * `height`, with no padding, so anything placed at `scale.toX(t)` lines up
   * with every other lane. This is where a custom lane plugs in, e.g. a
   * Recharts chart with zero horizontal margins and an x domain of
   * `[scale.view.start, scale.view.end]`.
   */
  children: React.ReactNode | ((args: LaneRenderArgs) => React.ReactNode)
}

/** One row of the timeline: fixed label gutter on the left, plot on the right. */
export function TimelineLane({ id, label, height, labelExtra, className, children }: TimelineLaneProps): JSX.Element | null {
  const hidden = useWorkspace((state) => state.hiddenLanes.includes(id))
  const scale = useTimeScale()
  if (hidden) return null
  return (
    <div data-lane={id} className={cn('flex border-b border-border/60 last:border-b-0', className)}>
      <div
        className="flex shrink-0 cursor-default items-center gap-1 border-r border-border/60 bg-muted/30 px-2.5 text-[11px] font-medium text-muted-foreground"
        style={{ width: TIMELINE_GUTTER_PX }}
      >
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {labelExtra}
      </div>
      <div className="relative min-w-0 flex-1 overflow-hidden" style={{ height }}>
        {typeof children === 'function' ? children({ scale, width: scale.width, height }) : children}
      </div>
    </div>
  )
}

const FOCUS_KEYS = ['ArrowLeft', 'ArrowRight', 'Home', 'End']

/**
 * Arrow-key navigation between the items of one lane. A lane is a single tab
 * stop; Left/Right/Home/End move focus between its items, Enter or Space
 * activates the focused one.
 */
function moveLaneFocus(event: React.KeyboardEvent<SVGSVGElement>): void {
  if (!FOCUS_KEYS.includes(event.key)) return
  const items = Array.from(event.currentTarget.querySelectorAll<SVGGElement>('[data-tl-item]'))
  const current = items.findIndex((item) => item === document.activeElement)
  const step = event.key === 'ArrowRight' ? 1 : -1
  const wanted = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : current + step
  const next = items[Math.min(Math.max(wanted, 0), items.length - 1)]
  if (!next) return
  event.preventDefault()
  next.focus()
}

export interface LaneSvgProps {
  /** Accessible name of the lane, e.g. "Segments". */
  label: string
  height: number
  children: React.ReactNode
}

/** SVG canvas for a lane with interactive items. Sized to the shared plot width. */
export function LaneSvg({ label, height, children }: LaneSvgProps): JSX.Element {
  const scale = useTimeScale()
  return (
    <svg
      role="group"
      aria-label={`${label} lane`}
      data-tl-arrows
      width={scale.width}
      height={height}
      className="block"
      onKeyDown={moveLaneFocus}
    >
      {children}
    </svg>
  )
}

export interface LaneItemProps {
  /** Full spoken description, e.g. "Segment: The kettle goes on, 0:07 to 0:12". */
  label: string
  selected?: boolean
  /** The first rendered item of a lane is its tab stop. */
  tabStop: boolean
  onActivate: () => void
  children: React.ReactNode
}

/**
 * Focusable, clickable SVG item. Give the main shape inside the class
 * `tl-shape`: focus and selection are shown on it (see `index.css`).
 */
export function LaneItem({ label, selected = false, tabStop, onActivate, children }: LaneItemProps): JSX.Element {
  const onKeyDown = (event: React.KeyboardEvent<SVGGElement>): void => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onActivate()
  }
  return (
    <g
      role="button"
      tabIndex={tabStop ? 0 : -1}
      aria-label={label}
      aria-pressed={selected}
      data-tl-item
      className="tl-item"
      onClick={onActivate}
      onKeyDown={onKeyDown}
    >
      <title>{label}</title>
      {children}
    </g>
  )
}
