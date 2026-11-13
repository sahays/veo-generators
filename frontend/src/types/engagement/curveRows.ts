import type { SignalPoint } from '@/types/insights'
import { downsampleForView } from '@/types/timeline/downsample'
import type { Viewport } from '@/types/timeline/viewport'
import type { ReportModel } from './reportModel'

/** One series of the curve lane. Values are drawn on a 0..1 axis: `lo` maps to 0 and `hi` to 1. */
export interface CurveSeries {
  /** Field of the chart rows that carries this series (the recharts `dataKey`). */
  key: string
  points: readonly SignalPoint[]
  lo: number
  hi: number
  /**
   * How long the last sample holds. When set, a closing row is added after it
   * so a step-after curve draws the final step instead of stopping at its start.
   */
  holdSec?: number
}

/** A chart row: the time plus the 0..1 height of every series that has a sample there. */
export type CurveRow = { t: number } & Record<string, number>

/** Position of `value` on the 0..1 axis of a series drawn over `[lo, hi]`. */
export function toUnit(value: number, lo: number, hi: number): number {
  const span = hi - lo
  return span > 0 ? (value - lo) / span : 0.5
}

function addSeriesRows(rows: Map<number, CurveRow>, series: CurveSeries, view: Viewport, widthPx: number): void {
  const put = (t: number, value: number): void => {
    const row = rows.get(t) ?? ({ t } as CurveRow)
    row[series.key] = toUnit(value, series.lo, series.hi)
    rows.set(t, row)
  }
  const visible = downsampleForView(series.points, view, widthPx)
  visible.forEach(([t, value]) => put(t, value))
  const last = series.points[series.points.length - 1]
  if (series.holdSec && last && visible[visible.length - 1] === last) put(last[0] + series.holdSec, last[1])
}

/**
 * Rows for the curve lane: each series reduced to about one point per pixel
 * of the visible range (peaks kept), scaled to its own range, and merged on
 * time. A row only carries the series that have a sample at its time, so draw
 * the series with `connectNulls`.
 */
export function buildCurveRows(series: readonly CurveSeries[], view: Viewport, widthPx: number): CurveRow[] {
  const rows = new Map<number, CurveRow>()
  series.forEach((item) => addSeriesRows(rows, item, view, widthPx))
  return [...rows.values()].sort((a, b) => a.t - b.t)
}

export type CurveRole = 'primary' | 'secondary' | 'smoothed'

/** A series of the curve lane with what the chart needs to draw and name it. */
export interface DrawnSeries extends CurveSeries {
  label: string
  color: string
  /** The primary metric is an area, other metrics are lines, the smoothed primary is a heavier line. */
  role: CurveRole
}

export const SMOOTHED_KEY = 'smooth'

/**
 * The series the curve lane draws: every metric that is not hidden, each
 * scaled to its own range, plus the smoothed primary metric when the report
 * smoothed it and the primary metric is visible.
 */
export function drawnSeries(model: ReportModel, hiddenMetrics: readonly string[], showSmoothed: boolean): DrawnSeries[] {
  const hidden = new Set(hiddenMetrics)
  const drawn: DrawnSeries[] = []
  model.metrics.forEach((metric, i) => {
    if (hidden.has(metric.key)) return
    const role: CurveRole = metric.primary ? 'primary' : 'secondary'
    drawn.push({ key: `m${i}`, points: metric.series.points, lo: metric.lo, hi: metric.hi, holdSec: model.interval, label: metric.label, color: metric.color, role })
  })
  if (showSmoothed && model.smoothing && !hidden.has(model.primary.key)) {
    const { lo, hi, label, color } = model.primary
    drawn.push({ key: SMOOTHED_KEY, points: model.smoothed, lo, hi, label: `${label} (smoothed)`, color, role: 'smoothed' })
  }
  return drawn
}
