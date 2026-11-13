import { Button } from '@/components/ui/button'
import { useSeek } from '@/hooks/timeline/timelineContext'
import { formatValue } from '@/types/engagement/reportFormat'
import { hookWindowSec, type ReportModel } from '@/types/engagement/reportModel'
import { percentDelta } from '@/types/engagement/stepSeries'
import type { TimelineModel } from '@/types/timeline/model'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge, EmptyProse } from '../ReportBits'
import { SegmentAverages } from './SegmentAverages'

interface KpiCardProps {
  label: string
  value: string
  /** Percent against the overall average, when that comparison means something. */
  deltaPct?: number | null
  /** Plain note under the value. */
  note?: string
  /** Time the figure occurs at; adds a button that seeks there. */
  timeSec?: number
}

function KpiCard({ label, value, deltaPct = null, note, timeSec }: KpiCardProps): JSX.Element {
  const seek = useSeek()
  return (
    <div data-testid={`kpi-${label.toLowerCase().replace(/\s+/g, '-')}`} className="space-y-1 rounded-lg border border-border/70 bg-muted/30 px-3 py-2.5">
      <dt className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xl font-semibold tabular-nums text-foreground">{value}</span>
        {deltaPct !== null && <DeltaBadge pct={deltaPct} />}
      </dd>
      <dd className="flex min-h-5 flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground">
        {note}
        {timeSec !== undefined && (
          <Button variant="link" className="text-[11px] text-accent-dark" aria-label={`${label}: go to ${formatTimecode(timeSec)}`} onClick={() => seek(timeSec)}>
            at {formatTimecode(timeSec)}
          </Button>
        )}
      </dd>
    </div>
  )
}

/** Headline figures of the primary metric. Each is a server-computed number from the report. */
function KpiCards({ report }: { report: ReportModel }): JSX.Element {
  const { kpis, signal, stats, duration_sec } = report.report
  const unit = signal.unit
  const versusAverage = (value: number | null | undefined): number | null => (value === null || value === undefined ? null : percentDelta(value, report.average))
  return (
    <dl className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
      <KpiCard label="Average" value={formatValue(kpis.avg, unit)} note={`median ${formatValue(stats.median, unit)}`} />
      <KpiCard label="Peak" value={formatValue(kpis.peak?.value, unit)} deltaPct={versusAverage(kpis.peak?.value)} timeSec={kpis.peak?.time_sec} />
      <KpiCard label="Lowest" value={formatValue(kpis.low?.value, unit)} deltaPct={versusAverage(kpis.low?.value)} timeSec={kpis.low?.time_sec} />
      <KpiCard label="Biggest drop" value={formatValue(kpis.biggest_drop?.delta, unit)} note={kpis.biggest_drop ? 'change over the decline' : 'no sharp drop found'} timeSec={kpis.biggest_drop?.time_sec} />
      <KpiCard label="Hook average" value={formatValue(kpis.hook_avg, unit)} deltaPct={versusAverage(kpis.hook_avg)} note={`first ${formatSpan(hookWindowSec(duration_sec))}`} />
    </dl>
  )
}

function Headline({ report }: { report: ReportModel }): JSX.Element {
  const headline = report.report.recommendations.headline
  if (!headline) {
    return <EmptyProse title="No headline was written.">The language-model step did not return a summary for this report. The figures and the curve are complete.</EmptyProse>
  }
  return <p data-testid="report-headline" className="text-sm font-medium leading-relaxed text-foreground">{headline}</p>
}

export interface OverviewTabProps {
  report: ReportModel
  timeline: TimelineModel
}

/** KPI cards, the headline and the average per segment. */
export function OverviewTab({ report, timeline }: OverviewTabProps): JSX.Element {
  return (
    <div className="space-y-4">
      <Headline report={report} />
      <KpiCards report={report} />
      <SegmentAverages report={report} timeline={timeline} />
    </div>
  )
}
