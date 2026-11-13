import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { ChartContainer, ChartTooltip, ChartTooltipContent, activeIndexOf, type ChartConfig } from '@/components/ui/chart'
import { usePrefersReducedMotion } from '@/hooks/timeline/usePrefersReducedMotion'
import { formatAxisValue, formatDelta, formatValue } from '@/types/engagement/reportFormat'
import type { ReportModel } from '@/types/engagement/reportModel'
import type { TimeRange } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge } from '../ReportBits'
import { useShowRange } from '../workspace/useFocusExtremum'

const CHART_CONFIG: ChartConfig = {
  avg: { label: 'Segment average' },
  above: { label: 'Above average', color: 'var(--chart-3)' },
  below: { label: 'Below average', color: 'var(--chart-6)' },
}

/** One segment with its statistics, in timeline order. */
interface SegmentRow extends TimeRange {
  id: string
  /** 1-based position in the video; the bar's axis label. */
  position: string
  title: string
  avg: number
  delta_pct: number
  rank: number
}

function segmentRows(report: ReportModel, timeline: TimelineModel): SegmentRow[] {
  return timeline.doc.segments.flatMap((segment, i) => {
    const stat = report.segmentStats.get(segment.id)
    if (!stat) return []
    return [{ id: segment.id, position: String(i + 1), title: segment.title, start_sec: segment.start_sec, end_sec: segment.end_sec, avg: stat.avg, delta_pct: stat.delta_pct, rank: stat.rank }]
  })
}

function tooltipRow(row: SegmentRow | undefined, unit: string): JSX.Element | null {
  if (!row) return null
  return (
    <div className="space-y-0.5">
      <p className="font-medium text-foreground">{row.position}. {row.title}</p>
      <p className="font-mono text-muted-foreground">{formatValue(row.avg, unit)} · {formatDelta(row.delta_pct)} vs average · rank {row.rank}</p>
      <p className="text-muted-foreground">{formatTimecode(row.start_sec)} – {formatTimecode(row.end_sec)}</p>
    </div>
  )
}

interface SegmentChartProps {
  rows: SegmentRow[]
  report: ReportModel
  onPick: (row: SegmentRow) => void
}

function SegmentChart({ rows, report, onPick }: SegmentChartProps): JSX.Element {
  const reducedMotion = usePrefersReducedMotion()
  const unit = report.report.signal.unit
  const pick = (index: number | null): void => {
    const row = index === null ? undefined : rows[index]
    if (row) onPick(row)
  }
  return (
    <ChartContainer config={CHART_CONFIG} className="aspect-auto h-[220px] w-full cursor-pointer" role="img" aria-label={`Average ${report.primary.label} of each of the ${rows.length} segments, against the overall average. The list next to the chart has the same figures.`}>
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }} onClick={(state) => pick(activeIndexOf(state))}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="position" tickLine={false} axisLine={false} />
        <YAxis tickLine={false} axisLine={false} tickCount={4} tickFormatter={formatAxisValue} />
        <ChartTooltip content={<ChartTooltipContent hideLabel formatter={(_value, _name, item) => tooltipRow(item.payload as SegmentRow | undefined, unit)} />} />
        <ReferenceLine y={report.average} stroke="var(--muted-foreground)" strokeDasharray="4 4" label={{ value: 'avg', position: 'insideTopRight', fontSize: 10, fill: 'var(--muted-foreground)' }} />
        <Bar dataKey="avg" radius={3} isAnimationActive={!reducedMotion}>
          {rows.map((row) => (
            <Cell key={row.id} fill={row.delta_pct >= 0 ? 'var(--color-above)' : 'var(--color-below)'} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

/** The same segments as buttons, best first: the keyboard path to what the chart does on click. */
function SegmentRanking({ rows, report, onPick }: SegmentChartProps): JSX.Element {
  const ranked = useMemo(() => [...rows].sort((a, b) => a.rank - b.rank), [rows])
  return (
    <ol aria-label="Segments by average, highest first" data-testid="segment-ranking" className="max-h-[236px] space-y-1 overflow-y-auto pr-1">
      {ranked.map((row) => (
        <li key={row.id}>
          <Button variant="unstyled" onClick={() => onPick(row)} className="flex w-full items-center gap-2 rounded-md border border-border/70 bg-card px-2.5 py-1.5 text-left text-xs hover:bg-muted/60">
            <span className="w-4 shrink-0 font-mono text-[10px] text-muted-foreground">{row.position}</span>
            <span className="min-w-0 flex-1 truncate font-medium text-foreground">{row.title}</span>
            <span className="font-mono tabular-nums text-muted-foreground">{formatValue(row.avg, report.report.signal.unit)}</span>
            <DeltaBadge pct={row.delta_pct} />
          </Button>
        </li>
      ))}
    </ol>
  )
}

export interface SegmentAveragesProps {
  report: ReportModel
  timeline: TimelineModel
}

/** Average of the primary metric per segment as a bar chart and a ranked list. Picking a segment seeks to it and zooms the timeline to it. */
export function SegmentAverages({ report, timeline }: SegmentAveragesProps): JSX.Element | null {
  const rows = useMemo(() => segmentRows(report, timeline), [report, timeline])
  const showRange = useShowRange()
  if (rows.length === 0) return null
  return (
    <figure data-testid="segment-chart" className="space-y-2">
      <figcaption className="text-xs font-semibold text-foreground">
        Average per segment <span className="font-normal text-muted-foreground">· numbers under the bars are the segments in order; click one to go to it</span>
      </figcaption>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <SegmentChart rows={rows} report={report} onPick={showRange} />
        <SegmentRanking rows={rows} report={report} onPick={showRange} />
      </div>
    </figure>
  )
}
