import type {
  EngagementReport,
  ExtremumKind,
  InfluenceKind,
  ReportExtremum,
  ReportInfluence,
  ReportMetric,
  ReportSegmentStat,
  SignalPoint,
  TimeRange,
} from '@/types/insights'
import { lowerBound } from '@/types/timeline/bisect'
import { chartColor, type Glyph } from '@/types/timeline/glyphs'
import { IntervalIndex, PointIndex } from '@/types/timeline/intervalIndex'
import type { TimelineItemRef } from '@/types/timeline/model'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { StepSeries } from './stepSeries'

/** Share of a metric's value span added above and below it when it is drawn. */
const RANGE_PAD_RATIO = 0.12
/** The report's "hook" is the opening tenth of the video, at most this long. */
const HOOK_MAX_SEC = 15
const HOOK_FRACTION = 0.1
/**
 * Palette slots of the metric curves (orange, violet, teal, yellow, slate).
 * Sky, emerald and rose are left to the valley, peak and drop markers.
 */
const METRIC_COLOR_SLOTS = [0, 3, 6, 4, 7]

/** One metric of the report with its lookup series, colour and drawing range. */
export interface MetricSeries {
  key: string
  label: string
  primary: boolean
  color: string
  series: StepSeries
  /** Value drawn at the bottom of the curve lane. */
  lo: number
  /** Value drawn at the top of the curve lane. */
  hi: number
}

/** An extremum addressable as a point on the timeline (`start_sec` is its `time_sec`). */
export interface ExtremumMarker extends ReportExtremum {
  start_sec: number
}

/** The context window of an extremum, for "which moment is the playhead inside". */
export interface ExtremumWindow extends TimeRange {
  extremum: ExtremumMarker
}

export interface InfluenceGroup {
  kind: InfluenceKind
  label: string
  items: ReportInfluence[]
}

/** An `EngagementReport` with every lookup structure built once. */
export interface ReportModel {
  report: EngagementReport
  interval: number
  metrics: MetricSeries[]
  primary: MetricSeries
  smoothed: readonly SignalPoint[]
  /** False when `smoothed` just repeats the primary metric (short series are not smoothed). */
  smoothing: boolean
  /** Overall average of the primary metric (`stats.avg`). */
  average: number
  /** Extrema in time order. */
  extrema: PointIndex<ExtremumMarker>
  extremumTimes: Float64Array
  extremumById: Map<string, ExtremumMarker>
  extremumWindows: IntervalIndex<ExtremumWindow>
  influenceByKey: Map<string, ReportInfluence>
  influenceGroups: InfluenceGroup[]
  segmentStats: Map<string, ReportSegmentStat>
  /** Extrema as selectable items, so `?sel=peak-1` in a link can be restored. */
  itemRefs: Map<string, TimelineItemRef>
}

export const EXTREMUM_STYLE: Record<ExtremumKind, { glyph: Glyph; label: string }> = {
  peak: { glyph: { shape: 'triangle', color: 'var(--chart-3)' }, label: 'Peak' },
  valley: { glyph: { shape: 'triangle-down', color: 'var(--chart-2)' }, label: 'Valley' },
  drop: { glyph: { shape: 'diamond', color: 'var(--chart-6)' }, label: 'Drop' },
}

const INFLUENCE_GROUPS: { kind: InfluenceKind; label: string }[] = [
  { kind: 'character', label: 'Characters' },
  { kind: 'object', label: 'Objects' },
  { kind: 'location', label: 'Locations' },
  { kind: 'emotion', label: 'Emotions' },
  { kind: 'event', label: 'Events' },
]

/** Title of an extremum; the report leaves it empty when the language-model step failed. */
export function extremumTitle(extremum: ReportExtremum): string {
  return extremum.title || `${EXTREMUM_STYLE[extremum.kind].label} at ${formatTimecode(extremum.time_sec)}`
}

/** `[lo, hi]` a metric is drawn over: its own value span plus some headroom, never below zero for non-negative data. */
export function displayRange(points: readonly SignalPoint[]): [number, number] {
  if (points.length === 0) return [0, 1]
  let min = Infinity
  let max = -Infinity
  for (const point of points) {
    min = Math.min(min, point[1])
    max = Math.max(max, point[1])
  }
  const pad = (max - min) * RANGE_PAD_RATIO || Math.abs(max) * RANGE_PAD_RATIO || 1
  return [min >= 0 ? Math.max(min - pad, 0) : min - pad, max + pad]
}

function metricSeries(metric: ReportMetric, index: number, interval: number): MetricSeries {
  const [lo, hi] = displayRange(metric.points)
  return {
    key: metric.key,
    label: metric.label,
    primary: metric.primary,
    color: chartColor(METRIC_COLOR_SLOTS[index % METRIC_COLOR_SLOTS.length]),
    series: new StepSeries(metric.points, interval),
    lo,
    hi,
  }
}

/** True when the two series are not point-for-point the same. */
function differs(a: readonly SignalPoint[], b: readonly SignalPoint[]): boolean {
  return a.length !== b.length || a.some((point, i) => point[0] !== b[i][0] || point[1] !== b[i][1])
}

function extremumRef(extremum: ExtremumMarker): TimelineItemRef {
  const range = { start_sec: extremum.time_sec, end_sec: extremum.time_sec }
  return { kind: 'extremum', id: extremum.id, label: extremumTitle(extremum), range }
}

function groupInfluence(influence: readonly ReportInfluence[]): InfluenceGroup[] {
  const byKind = new Map<InfluenceKind, ReportInfluence[]>()
  influence.forEach((entry) => {
    const items = byKind.get(entry.kind)
    if (items) items.push(entry)
    else byKind.set(entry.kind, [entry])
  })
  return INFLUENCE_GROUPS.flatMap(({ kind, label }) => {
    const items = byKind.get(kind)
    return items ? [{ kind, label, items }] : []
  })
}

export function buildReportModel(report: EngagementReport): ReportModel {
  const interval = report.signal.interval_sec > 0 ? report.signal.interval_sec : 1
  const metrics = report.metrics.map((metric, i) => metricSeries(metric, i, interval))
  const primary = metrics.find((metric) => metric.primary) ?? metrics[0] ?? metricSeries({ key: 'signal', label: report.signal.label, primary: true, points: [] }, 0, interval)
  const extrema = new PointIndex(report.extrema.map((extremum) => ({ ...extremum, start_sec: extremum.time_sec })))
  return {
    report,
    interval,
    metrics,
    primary,
    smoothed: report.smoothed,
    smoothing: differs(report.smoothed, primary.series.points),
    average: report.stats.avg,
    extrema,
    extremumTimes: Float64Array.from(extrema.items, (extremum) => extremum.start_sec),
    extremumById: new Map(extrema.items.map((extremum) => [extremum.id, extremum])),
    extremumWindows: new IntervalIndex(extrema.items.map((extremum) => ({ ...extremum.window, extremum }))),
    influenceByKey: new Map(report.influence.map((entry) => [entry.key, entry])),
    influenceGroups: groupInfluence(report.influence),
    segmentStats: new Map(report.segments.map((stat) => [stat.segment_id, stat])),
    itemRefs: new Map(extrema.items.map((extremum) => [extremum.id, extremumRef(extremum)])),
  }
}

/** The extremum closest in time to `t` (the earlier one on a tie), or null when there are none. */
export function nearestExtremum(model: ReportModel, t: number): ExtremumMarker | null {
  const after = lowerBound(model.extremumTimes, t)
  const next = model.extrema.items[after]
  const previous = model.extrema.items[after - 1]
  if (!next || !previous) return next ?? previous ?? null
  return t - previous.start_sec <= next.start_sec - t ? previous : next
}

/** Length of the opening the report's `hook_avg` is measured over. */
export function hookWindowSec(durationSec: number): number {
  return Math.min(HOOK_MAX_SEC, HOOK_FRACTION * Math.max(durationSec, 0))
}

/**
 * The extremum the playhead is "at": of the extrema whose context window
 * contains `t`, the one closest in time (the first in report order on a tie,
 * so a peak wins over the drop that starts on it). Null outside every window.
 */
export function extremumInContext(model: ReportModel, t: number): ExtremumMarker | null {
  let best: ExtremumMarker | null = null
  for (const { extremum } of model.extremumWindows.at(t)) {
    if (!best || Math.abs(extremum.time_sec - t) < Math.abs(best.time_sec - t)) best = extremum
  }
  return best
}
