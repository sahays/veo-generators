import { useMemo } from 'react'
import { Area, ComposedChart, Line, ReferenceDot, ReferenceLine, XAxis, YAxis } from 'recharts'
import { TimelineLane, type LaneRenderArgs } from '@/components/shared/timeline'
import { ChartContainer, type ChartConfig } from '@/components/ui/chart'
import { NO_PAN_ATTR } from '@/hooks/timeline/useTimelineGestures'
import { useTimeScrub } from '@/hooks/timeline/useTimeScrub'
import { buildCurveRows, drawnSeries, toUnit, type DrawnSeries } from '@/types/engagement/curveRows'
import { formatValue, reportBadgeText } from '@/types/engagement/reportFormat'
import { EXTREMUM_STYLE, type ReportModel } from '@/types/engagement/reportModel'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { SignalBadge } from '../SignalBadge'
import { DriverShading } from './DriverLanes'
import { useEngagementUi } from './engagementUi'

export const CURVE_LANE_ID = 'engagement'
const HEIGHT = 172
/**
 * No horizontal margins: with the x domain bound to the visible range, the
 * chart's plot box is then exactly the lane's plot box, so a time lands at
 * the same x here as in every other lane.
 */
const MARGIN = { top: 10, right: 0, bottom: 0, left: 0 }
const UNIT_DOMAIN = [0, 1]
const GRADIENT_ID = 'engagement-curve-fill'
/** Label of the average line: inside the plot at its right end, with a halo so the curve does not cut through it. */
const AVERAGE_LABEL = { position: 'insideBottomRight', fontSize: 10, fill: 'var(--muted-foreground)', stroke: 'var(--card)', strokeWidth: 3, paintOrder: 'stroke' } as const
/** Dash patterns of the secondary metrics, so they differ by more than colour. */
const SECONDARY_DASHES = ['6 3', '2 3', '8 3 2 3']

function chartConfig(series: readonly DrawnSeries[]): ChartConfig {
  return Object.fromEntries(series.map((item) => [item.key, { label: item.label, color: item.color }]))
}

/** The raw primary metric is a stepped area (each value holds for one interval), its smoothed form a heavier line, other metrics dashed stepped lines. */
function seriesElement(item: DrawnSeries, position: number): JSX.Element {
  const color = `var(--color-${item.key})`
  const shared = { dataKey: item.key, stroke: color, connectNulls: true, isAnimationActive: false, activeDot: false } as const
  if (item.role === 'primary') return <Area key={item.key} {...shared} type="stepAfter" strokeWidth={1.5} fill={`url(#${GRADIENT_ID})`} />
  if (item.role === 'smoothed') return <Line key={item.key} {...shared} type="monotone" strokeWidth={2.25} dot={false} />
  return <Line key={item.key} {...shared} type="stepAfter" strokeWidth={1.5} strokeDasharray={SECONDARY_DASHES[position % SECONDARY_DASHES.length]} dot={false} />
}

/** Dots on the curve at the report's peaks, valleys and drops. Drawn by the chart, so they also prove its x mapping. */
function extremumDots(report: ReportModel): JSX.Element[] {
  const { lo, hi } = report.primary
  return report.extrema.items.map((extremum) => (
    <ReferenceDot key={extremum.id} x={extremum.time_sec} y={toUnit(extremum.value, lo, hi)} r={3.5} fill={EXTREMUM_STYLE[extremum.kind].glyph.color} stroke="var(--card)" strokeWidth={1.5} ifOverflow="discard" />
  ))
}

function curveSummary(report: ReportModel): string {
  const { signal, kpis } = report.report
  const peak = kpis.peak ? ` Highest ${formatValue(kpis.peak.value, signal.unit)} at ${formatTimecode(kpis.peak.time_sec)}.` : ''
  const low = kpis.low ? ` Lowest ${formatValue(kpis.low.value, signal.unit)} at ${formatTimecode(kpis.low.time_sec)}.` : ''
  return `Engagement curve, ${report.primary.label}. Average ${formatValue(report.average, signal.unit)}.${peak}${low} The Data tab lists every value.`
}

interface CurveChartProps extends LaneRenderArgs {
  report: ReportModel
  series: readonly DrawnSeries[]
}

function CurveChart({ report, series, scale, width, height }: CurveChartProps): JSX.Element {
  const rows = useMemo(() => buildCurveRows(series, scale.view, width), [series, scale.view, width])
  const config = useMemo(() => chartConfig(series), [series])
  const primary = series.find((item) => item.role === 'primary')
  const unit = report.report.signal.unit
  return (
    <ChartContainer config={config} className="aspect-auto" style={{ width, height }} role="img" aria-label={curveSummary(report)}>
      <ComposedChart data={rows} margin={MARGIN} accessibilityLayer={false}>
        <defs>
          <linearGradient id={GRADIENT_ID} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={report.primary.color} stopOpacity={0.55} />
            <stop offset="100%" stopColor={report.primary.color} stopOpacity={0.08} />
          </linearGradient>
        </defs>
        <XAxis type="number" dataKey="t" hide allowDataOverflow domain={[scale.view.start, scale.view.end]} />
        <YAxis hide allowDataOverflow domain={UNIT_DOMAIN} />
        {series.map((item, i) => seriesElement(item, i))}
        {primary && (
          <ReferenceLine y={toUnit(report.average, primary.lo, primary.hi)} stroke="var(--muted-foreground)" strokeDasharray="4 4" label={{ ...AVERAGE_LABEL, value: `avg ${formatValue(report.average, unit)}` }} />
        )}
        {primary && extremumDots(report)}
      </ComposedChart>
    </ChartContainer>
  )
}

/** Value labels of the primary metric's range, drawn inside the plot (the chart itself has no left margin). */
function RangeLabels({ report }: { report: ReportModel }): JSX.Element {
  const unit = report.report.signal.unit
  const labelClass = 'pointer-events-none absolute left-1.5 rounded bg-card/75 px-1 font-mono text-[10px] tabular-nums text-muted-foreground'
  return (
    <>
      <span aria-hidden className={`${labelClass} top-0.5`}>{formatValue(report.primary.hi, unit)}</span>
      <span aria-hidden className={`${labelClass} bottom-0.5`}>{formatValue(report.primary.lo, unit)}</span>
    </>
  )
}

function CurvePlot({ report, scale, width, height }: LaneRenderArgs & { report: ReportModel }): JSX.Element {
  const hiddenMetrics = useEngagementUi((state) => state.hiddenMetrics)
  const showSmoothed = useEngagementUi((state) => state.showSmoothed)
  const series = useMemo(() => drawnSeries(report, hiddenMetrics, showSmoothed), [report, hiddenMetrics, showSmoothed])
  const scrub = useTimeScrub()
  const primaryVisible = series.some((item) => item.role === 'primary')
  return (
    <div data-testid="curve-plot" {...{ [NO_PAN_ATTR]: '' }} className="absolute inset-0 cursor-crosshair touch-none" {...scrub}>
      <DriverShading report={report} height={height} />
      {width > 0 && <CurveChart report={report} series={series} scale={scale} width={width} height={height} />}
      {primaryVisible && <RangeLabels report={report} />}
      {report.report.signal.simulated && (
        <span className="pointer-events-none absolute right-2 top-1.5">
          <SignalBadge text={reportBadgeText(report.report.signal)} compact className="bg-card/90" />
        </span>
      )}
    </div>
  )
}

function CurveLabel({ report }: { report: ReportModel }): JSX.Element {
  return (
    <span className="block leading-tight">
      Engagement
      <span className="block truncate text-[10px] font-normal" title={report.primary.label}>{report.primary.label}</span>
    </span>
  )
}

/**
 * The engagement curve as a timeline lane: a recharts chart (through the
 * shadcn chart primitive) whose x axis is the shared visible range. Click or
 * drag anywhere on it to scrub; Shift-drag selects a range.
 */
export function CurveLane({ report }: { report: ReportModel }): JSX.Element {
  return (
    <TimelineLane id={CURVE_LANE_ID} label={<CurveLabel report={report} />} height={HEIGHT}>
      {(args) => <CurvePlot report={report} {...args} />}
    </TimelineLane>
  )
}
