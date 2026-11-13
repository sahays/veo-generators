import { useCallback } from 'react'
import { GlyphIcon, NowStrip } from '@/components/shared/timeline'
import { Button } from '@/components/ui/button'
import { useTimelineKit } from '@/hooks/timeline/timelineContext'
import { useClockValue } from '@/hooks/timeline/useMediaClock'
import { formatValue, reportBadgeText } from '@/types/engagement/reportFormat'
import { EXTREMUM_STYLE, extremumInContext, extremumTitle, type ExtremumMarker, type ReportModel } from '@/types/engagement/reportModel'
import { percentDelta } from '@/types/engagement/stepSeries'
import type { TimelineModel } from '@/types/timeline/model'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge } from '../ReportBits'
import { SignalBadge } from '../SignalBadge'
import { useFocusExtremum } from './useFocusExtremum'

const sameIndex = (index: number): number => index
const extremumId = (extremum: ExtremumMarker | null): string | null => extremum?.id ?? null

/** Share of the way from `min` to `max`, as a CSS percentage. */
function gaugePosition(value: number, min: number, max: number): string {
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  return `${Math.min(Math.max(ratio, 0), 1) * 100}%`
}

/** Where the current value sits between the lowest and highest value of the curve, with the average marked. */
function ValueGauge({ value, report }: { value: number; report: ReportModel }): JSX.Element {
  const { min, max, avg } = report.report.stats
  return (
    <div aria-hidden className="relative h-1.5 rounded-full bg-foreground/15">
      <span className="absolute -top-1 h-3.5 w-px bg-muted-foreground" style={{ left: gaugePosition(avg, min, max) }} />
      <span className="absolute -top-0.5 h-2.5 w-2.5 -translate-x-1/2 rounded-full border-2 border-card bg-accent" style={{ left: gaugePosition(value, min, max) }} />
    </div>
  )
}

/**
 * Value of the primary metric at the playhead and its distance from the
 * average. Subscribes to the clock through a sample lookup, so it re-renders
 * when the playhead enters another sample, not on every frame.
 */
function ValueNow({ report }: { report: ReportModel }): JSX.Element {
  const { clock } = useTimelineKit()
  const series = report.primary.series
  const sampleAt = useCallback((timeSec: number) => series.indexAt(timeSec), [series])
  const index = useClockValue(clock, sampleAt, sameIndex)
  const value = index < 0 ? null : series.points[index][1]
  const unit = report.report.signal.unit
  return (
    <div data-testid="moment-value" className="space-y-2">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
        <span className="font-mono text-3xl font-semibold tabular-nums leading-none text-foreground">{formatValue(value, unit)}</span>
        {value !== null && <DeltaBadge pct={percentDelta(value, report.average)} />}
        <span className="text-[11px] text-muted-foreground">
          {value === null ? 'No sample at this time' : `vs average ${formatValue(report.average, unit)}`}
        </span>
      </div>
      <p className="text-[11px] text-muted-foreground">{report.primary.label}</p>
      {value !== null && <ValueGauge value={value} report={report} />}
    </div>
  )
}

/**
 * The peak, valley or drop whose context window contains the playhead, with
 * its explanation. The slot keeps its height when there is none, so the panel
 * does not jump during playback.
 */
function MomentContext({ report }: { report: ReportModel }): JSX.Element {
  const { clock } = useTimelineKit()
  const focus = useFocusExtremum()
  const windowAt = useCallback((timeSec: number) => extremumInContext(report, timeSec), [report])
  const extremum = useClockValue(clock, windowAt, extremumId)
  if (!extremum) {
    return <p data-testid="moment-context" className="flex h-20 items-center rounded-lg border border-dashed border-border/70 px-3 text-[11px] text-muted-foreground">Not near a peak, valley or drop.</p>
  }
  const style = EXTREMUM_STYLE[extremum.kind]
  return (
    <Button variant="unstyled" data-testid="moment-context" onClick={() => focus(extremum)} className="block h-20 w-full overflow-hidden rounded-lg border border-border/70 bg-muted/30 px-3 py-2 text-left text-xs hover:bg-muted/60">
      <span className="flex items-center gap-1.5 font-semibold text-foreground">
        <GlyphIcon shape={style.glyph.shape} color={style.glyph.color} />
        <span className="min-w-0 flex-1 truncate">{extremumTitle(extremum)}</span>
        <span className="shrink-0 font-mono text-[10px] font-normal text-muted-foreground">{style.label} · {formatTimecode(extremum.time_sec)}</span>
      </span>
      <span className="mt-1 line-clamp-2 block leading-snug text-muted-foreground">{extremum.explanation || 'No explanation was written for this moment.'}</span>
    </Button>
  )
}

export interface SidePanelProps {
  label: string
  testId: string
  children: React.ReactNode
}

/**
 * A panel next to the player with a fixed size: the height of the player's
 * row on wide screens, a set height when the panels stack. It scrolls inside,
 * so nothing it shows (a selected range, another cue) can move the timeline
 * underneath, not even in the middle of a drag on the ruler.
 */
export function SidePanel({ label, testId, children }: SidePanelProps): JSX.Element {
  return (
    <section aria-label={label} data-testid={testId} className="relative h-72 min-w-0 rounded-xl border border-border bg-card xl:h-auto xl:min-h-[17rem]">
      <div className="absolute inset-0 space-y-3 overflow-y-auto p-4">{children}</div>
    </section>
  )
}

export interface MomentPanelProps {
  report: ReportModel
  timeline: TimelineModel
}

/** "At this moment": the curve's value at the playhead against the average, and what is on screen there. */
export function MomentPanel({ report, timeline }: MomentPanelProps): JSX.Element {
  return (
    <SidePanel label="At this moment" testId="moment-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">At this moment</h3>
        <SignalBadge text={reportBadgeText(report.report.signal)} compact />
      </div>
      <ValueNow report={report} />
      <MomentContext report={report} />
      <NowStrip model={timeline} className="border-0 bg-transparent px-0 py-0" />
    </SidePanel>
  )
}
