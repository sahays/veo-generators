import { Check, Layers, Maximize2, ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { useTimelineKit, useTimelineView, useWorkspace } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'
import { isFitted } from '@/types/timeline/viewport'

const ZOOM_STEP = 1.6

export interface LaneOption {
  /** The `id` of a lane (or `ENTITY_LANES_ID` for all pinned-entity lanes). */
  id: string
  label: string
}

function LaneToggleItem({ lane }: { lane: LaneOption }): JSX.Element {
  const { store } = useTimelineKit()
  const visible = useWorkspace((state) => !state.hiddenLanes.includes(lane.id))
  return (
    <DropdownMenuItem
      role="menuitemcheckbox"
      aria-checked={visible}
      onSelect={(event) => {
        event.preventDefault()
        store.getState().toggleLane(lane.id)
      }}
    >
      <span className="flex items-center gap-2">
        <Check size={13} className={cn('shrink-0 text-accent', !visible && 'invisible')} />
        {lane.label}
      </span>
    </DropdownMenuItem>
  )
}

/** Menu of checkboxes to show or hide individual lanes. */
export function LaneToggleMenu({ lanes }: { lanes: readonly LaneOption[] }): JSX.Element {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" icon={Layers} aria-label="Show or hide lanes">
          Lanes
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Visible lanes</DropdownMenuLabel>
        {lanes.map((lane) => (
          <LaneToggleItem key={lane.id} lane={lane} />
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Zoom out, zoom in and fit. Zooming keeps the centre of the view fixed. */
export function ZoomControls(): JSX.Element {
  const { viewport, duration } = useTimelineKit()
  const view = useTimelineView()
  return (
    <div role="group" aria-label="Zoom" className="flex items-center gap-1">
      <Button variant="outline" size="icon" aria-label="Zoom out" onClick={() => viewport.zoomBy(1 / ZOOM_STEP)} disabled={isFitted(view, duration)}>
        <ZoomOut size={14} />
      </Button>
      <Button variant="outline" size="icon" aria-label="Zoom in" onClick={() => viewport.zoomBy(ZOOM_STEP)}>
        <ZoomIn size={14} />
      </Button>
      <Button variant="outline" size="sm" icon={Maximize2} aria-label="Fit whole video" onClick={viewport.fit} disabled={isFitted(view, duration)}>
        Fit
      </Button>
    </div>
  )
}

function VisibleRange(): JSX.Element {
  const view = useTimelineView()
  const tenths = view.end - view.start < 20
  return (
    <span data-testid="timeline-visible-range" className="font-mono text-[11px] text-muted-foreground" aria-live="off">
      {formatTimecode(view.start, { tenths })} – {formatTimecode(view.end, { tenths })}
      <span className="ml-1.5 text-muted-foreground/70">({formatSpan(view.end - view.start)})</span>
    </span>
  )
}

function FollowToggle(): JSX.Element {
  const { store } = useTimelineKit()
  const follow = useWorkspace((state) => state.followPlayhead)
  return (
    <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground">
      <Switch checked={follow} onCheckedChange={store.getState().setFollowPlayhead} aria-label="Follow the playhead during playback" />
      Follow
    </label>
  )
}

export interface TimelineToolbarProps {
  /** Lanes offered in the show/hide menu. Omit to hide the menu. */
  lanes?: readonly LaneOption[]
  /** Extra controls placed at the start of the toolbar (e.g. metric toggles). */
  children?: React.ReactNode
  className?: string
}

/** Controls for a timeline: visible-range readout, follow toggle, lane toggles, zoom and fit. */
export function TimelineToolbar({ lanes, children, className }: TimelineToolbarProps): JSX.Element {
  return (
    <div role="toolbar" aria-label="Timeline controls" className={cn('flex flex-wrap items-center gap-x-3 gap-y-2', className)}>
      {children}
      <VisibleRange />
      <div className="ml-auto flex flex-wrap items-center gap-3">
        <FollowToggle />
        {lanes && lanes.length > 0 && <LaneToggleMenu lanes={lanes} />}
        <ZoomControls />
      </div>
    </div>
  )
}
