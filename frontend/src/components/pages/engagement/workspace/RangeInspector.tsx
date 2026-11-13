import { useMemo } from 'react'
import { Maximize2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimelineSelection } from '@/store/timeline/workspaceStore'
import { summariseRange, type RangeSummary } from '@/types/engagement/rangeSummary'
import { formatValue } from '@/types/engagement/reportFormat'
import type { ReportModel } from '@/types/engagement/reportModel'
import type { TimelineCue } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge } from '../ReportBits'
import { SidePanel } from './MomentPanel'

const MAX_CUES = 5
const MAX_ENTITIES = 8
/** Shorter gaps than this between the range and the signal's coverage are not worth a note. */
const COVERAGE_TOLERANCE_SEC = 0.05

function RangeAverage({ summary, report }: { summary: RangeSummary; report: ReportModel }): JSX.Element {
  const unit = report.report.signal.unit
  const length = summary.range.end_sec - summary.range.start_sec
  const partial = summary.coveredSec < length - COVERAGE_TOLERANCE_SEC
  return (
    <div data-testid="range-average" className="space-y-1">
      <h5 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Average in range</h5>
      <p className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xl font-semibold tabular-nums text-foreground">{formatValue(summary.average, unit)}</span>
        {summary.deltaPct !== null && <DeltaBadge pct={summary.deltaPct} />}
      </p>
      <p className="text-[11px] text-muted-foreground">
        Overall average {formatValue(report.average, unit)}
        {summary.average === null && ' · the signal has no samples in this range'}
        {summary.average !== null && partial && ` · the signal covers ${formatSpan(summary.coveredSec)} of this range`}
      </p>
    </div>
  )
}

function RangeEntities({ summary }: { summary: RangeSummary }): JSX.Element {
  const shown = summary.entities.slice(0, MAX_ENTITIES)
  return (
    <div className="space-y-1">
      <h5 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">On screen</h5>
      {shown.length === 0 && <p className="text-[11px] text-muted-foreground">No one on screen</p>}
      <ul aria-label="On screen in this range" className="flex flex-wrap gap-1">
        {shown.map(({ entity, seconds }) => (
          <li key={entity.id}>
            <Badge variant={entity.kind === 'character' ? 'accent' : 'default'}>
              {entity.name} <span className="font-mono font-normal opacity-80">{formatSpan(seconds)}</span>
            </Badge>
          </li>
        ))}
        {summary.entities.length > MAX_ENTITIES && <li><Badge variant="outline">+{summary.entities.length - MAX_ENTITIES}</Badge></li>}
      </ul>
    </div>
  )
}

function CueRow({ cue }: { cue: TimelineCue }): JSX.Element {
  const spoken = cue.kind === 'dialogue' || cue.kind === 'narration'
  return (
    <li className="flex gap-2 text-[11px] leading-snug">
      <span className="shrink-0 font-mono text-muted-foreground">{formatTimecode(cue.start_sec)}</span>
      <span className={spoken ? 'text-foreground' : 'italic text-muted-foreground'}>
        {cue.speaker && <span className="font-semibold text-accent-dark">{cue.speaker}: </span>}
        {spoken ? cue.text : `[${cue.text}]`}
      </span>
    </li>
  )
}

function RangeCues({ summary }: { summary: RangeSummary }): JSX.Element {
  return (
    <div className="space-y-1">
      <h5 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Cues ({summary.cues.length})</h5>
      {summary.cues.length === 0 && <p className="text-[11px] text-muted-foreground">No dialogue or sound cue</p>}
      <ul aria-label="Cues in this range" className="space-y-0.5">
        {summary.cues.slice(0, MAX_CUES).map((cue) => <CueRow key={cue.id} cue={cue} />)}
      </ul>
      {summary.cues.length > MAX_CUES && <p className="text-[11px] text-muted-foreground">+{summary.cues.length - MAX_CUES} more</p>}
    </div>
  )
}

interface RangeDetailsProps {
  selection: TimelineSelection
  report: ReportModel
  timeline: TimelineModel
}

function RangeDetails({ selection, report, timeline }: RangeDetailsProps): JSX.Element {
  const { store, viewport } = useTimelineKit()
  const { start_sec, end_sec } = selection.range
  const summary = useMemo(() => summariseRange(report, timeline, { start_sec, end_sec }), [report, timeline, start_sec, end_sec])
  return (
    <>
      <div className="space-y-1.5">
        <h4 className="truncate text-sm font-semibold text-foreground" title={selection.label}>{selection.label}</h4>
        <p data-testid="range-span" className="font-mono text-[11px] text-muted-foreground">
          {formatTimecode(start_sec, { tenths: true })} – {formatTimecode(end_sec, { tenths: true })} ({formatSpan(end_sec - start_sec)})
        </p>
        <div className="flex flex-wrap gap-1.5">
          <Button variant="outline" size="xs" icon={Maximize2} onClick={() => viewport.showRange(selection.range)}>Zoom to range</Button>
          <Button variant="ghost" size="xs" icon={X} onClick={() => store.getState().select(null)}>Clear</Button>
        </div>
      </div>
      <RangeAverage summary={summary} report={report} />
      <RangeEntities summary={summary} />
      <RangeCues summary={summary} />
    </>
  )
}

export interface RangeInspectorProps {
  report: ReportModel
  timeline: TimelineModel
}

/**
 * Summary of the selected time range: its average against the overall
 * average, who is on screen and the cues inside it. Works for a range dragged
 * with Shift on the ruler or the curve and for any selected item that has a
 * length (a segment, an emotion span, a driver's range).
 */
export function RangeInspector({ report, timeline }: RangeInspectorProps): JSX.Element {
  const selection = useWorkspace((state) => state.selection)
  const ranged = selection && selection.range.end_sec > selection.range.start_sec ? selection : null
  return (
    <SidePanel label="Range inspector" testId="range-inspector">
      <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Range inspector</h3>
      {ranged ? (
        <RangeDetails selection={ranged} report={report} timeline={timeline} />
      ) : (
        <p className="text-xs leading-relaxed text-muted-foreground">
          Shift-drag on the ruler or the curve, or click a segment, to compare that stretch with the overall average and see who is on screen and what is said in it.
        </p>
      )}
    </SidePanel>
  )
}
