import { Eye, EyeOff } from 'lucide-react'
import {
  EmotionsLane,
  ENTITY_LANES_ID,
  EntityLanes,
  KeyMomentsLane,
  MarkersLane,
  Minimap,
  MomentHoverCard,
  RulerLane,
  SegmentsLane,
  TimelineSurface,
  TimelineToolbar,
  type LaneOption,
  type MarkerStyle,
} from '@/components/shared/timeline'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { describeDelta, formatDelta, formatValue } from '@/types/engagement/reportFormat'
import { EXTREMUM_STYLE, extremumTitle, type ExtremumMarker, type MetricSeries, type ReportModel } from '@/types/engagement/reportModel'
import { percentDelta } from '@/types/engagement/stepSeries'
import type { TimelineModel } from '@/types/timeline/model'
import { CURVE_LANE_ID, CurveLane } from './CurveLane'
import { DRIVER_LANES_ID, DriverLanes } from './DriverLanes'
import { useEngagementUi, useEngagementUiStore } from './engagementUi'

const EXTREMA_LANE_ID = 'extrema'

const LANE_OPTIONS: LaneOption[] = [
  { id: CURVE_LANE_ID, label: 'Engagement curve' },
  { id: EXTREMA_LANE_ID, label: 'Peaks, valleys and drops' },
  { id: DRIVER_LANES_ID, label: 'Selected drivers' },
  { id: 'segments', label: 'Segments' },
  { id: 'moments', label: 'Key moments' },
  { id: 'emotions', label: 'Emotions' },
  { id: ENTITY_LANES_ID, label: 'Pinned entities' },
]

/** Glyph (shape and colour per kind) and spoken description of an extremum marker. A drop is described by the size of its fall. */
function describeExtremum(extremum: ExtremumMarker): MarkerStyle {
  const style = EXTREMUM_STYLE[extremum.kind]
  const figure = extremum.kind === 'drop' ? `falls ${formatValue(extremum.prominence)}` : describeDelta(extremum.delta_pct)
  return { glyph: style.glyph, description: `${style.label}: ${extremumTitle(extremum)}, ${figure}` }
}

interface ToggleChipProps {
  label: string
  color: string
  pressed: boolean
  onToggle: () => void
}

/** Show/hide switch for one curve. The eye icon carries the state, not only the colour. */
function ToggleChip({ label, color, pressed, onToggle }: ToggleChipProps): JSX.Element {
  const Icon = pressed ? Eye : EyeOff
  return (
    <Button variant="outline" size="xs" aria-pressed={pressed} title={pressed ? `Hide ${label}` : `Show ${label}`} onClick={onToggle} className={cn('gap-1.5', !pressed && 'opacity-60')}>
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
      <span className="max-w-[10rem] truncate">{label}</span>
      <Icon size={12} aria-hidden />
    </Button>
  )
}

/** Toggles for the curves of the lane: one per metric when the report has several, and the smoothed line when there is one. */
function CurveToggles({ report }: { report: ReportModel }): JSX.Element | null {
  const store = useEngagementUiStore()
  const hiddenMetrics = useEngagementUi((state) => state.hiddenMetrics)
  const showSmoothed = useEngagementUi((state) => state.showSmoothed)
  const metrics = report.metrics.length > 1 ? report.metrics : []
  if (metrics.length === 0 && !report.smoothing) return null
  return (
    <div role="group" aria-label="Curves" data-testid="curve-toggles" className="flex flex-wrap items-center gap-1.5">
      {metrics.map((metric) => (
        <ToggleChip key={metric.key} label={metric.label} color={metric.color} pressed={!hiddenMetrics.includes(metric.key)} onToggle={() => store.getState().toggleMetric(metric.key)} />
      ))}
      {report.smoothing && <ToggleChip label="Smoothed" color={report.primary.color} pressed={showSmoothed} onToggle={() => store.getState().setShowSmoothed(!showSmoothed)} />}
    </div>
  )
}

interface MetricReadingProps {
  metric: MetricSeries
  timeSec: number
  report: ReportModel
}

/** The true (unscaled) value of one metric at a time; the primary metric also shows its distance from the average. */
function MetricReading({ metric, timeSec, report }: MetricReadingProps): JSX.Element {
  const value = metric.series.valueAt(timeSec)
  const delta = metric.primary && value !== null ? percentDelta(value, report.average) : null
  return (
    <li className="flex items-center gap-1.5">
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: metric.color }} />
      <span className="min-w-0 flex-1 truncate text-muted-foreground">{metric.label}</span>
      <span className="font-mono font-semibold tabular-nums text-foreground">{formatValue(value, metric.primary ? report.report.signal.unit : '')}</span>
      {delta !== null && <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{formatDelta(delta)}</span>}
    </li>
  )
}

interface EngagementHoverCardProps {
  report: ReportModel
  timeline: TimelineModel
  timeSec: number
}

/** Hover card: the value of every visible metric at the cursor, then what is happening in the video there. */
function EngagementHoverCard({ report, timeline, timeSec }: EngagementHoverCardProps): JSX.Element {
  const hiddenMetrics = useEngagementUi((state) => state.hiddenMetrics)
  const visible = report.metrics.filter((metric) => !hiddenMetrics.includes(metric.key))
  return (
    <div className="space-y-2">
      <ul data-testid="hover-metrics" className="space-y-0.5 border-b border-border/60 pb-2">
        {visible.map((metric) => (
          <MetricReading key={metric.key} metric={metric} timeSec={timeSec} report={report} />
        ))}
      </ul>
      <MomentHoverCard model={timeline} timeSec={timeSec} />
    </div>
  )
}

export interface EngagementTimelineProps {
  report: ReportModel
  timeline: TimelineModel
}

/** The Engagement timeline: the curve and its markers on top, the scene lanes underneath, all on one scale. */
export function EngagementTimeline({ report, timeline }: EngagementTimelineProps): JSX.Element {
  return (
    <section aria-label="Timeline" className="space-y-2">
      <TimelineToolbar lanes={LANE_OPTIONS}>
        <CurveToggles report={report} />
      </TimelineToolbar>
      <TimelineSurface ariaLabel="Engagement timeline" hoverCard={(timeSec) => <EngagementHoverCard report={report} timeline={timeline} timeSec={timeSec} />}>
        <RulerLane />
        <CurveLane report={report} />
        <MarkersLane id={EXTREMA_LANE_ID} label="Peaks & valleys" kind="extremum" points={report.extrema} describe={describeExtremum} rows={2} height={36} />
        <DriverLanes report={report} />
        <SegmentsLane segments={timeline.segments} />
        <KeyMomentsLane points={timeline.moments} />
        <EmotionsLane index={timeline.emotions} />
        <EntityLanes entityById={timeline.entityById} entityRanges={timeline.entityRanges} />
      </TimelineSurface>
      <Minimap ranges={timeline.doc.segments} />
      <p className="text-[11px] text-muted-foreground">
        Click or drag the curve or the ruler to scrub; Shift-drag either to select a range. Scroll to zoom at the cursor, drag a lane to pan. Scene timestamps come from the model and are approximate.
      </p>
    </section>
  )
}
