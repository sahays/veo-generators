import type { EngagementReport, ReportExtremum, ReportInfluence, SignalPoint } from '@/types/insights'
import { toCsv, type CsvValue } from '@/types/timeline/exporters'

/**
 * CSV exports of an engagement report, generated in the browser from the
 * loaded document. Every cell goes through the kit's `toCsv`, which
 * neutralises text a spreadsheet would run as a formula.
 */

function setColumn(rows: Map<number, CsvValue[]>, width: number, column: number, points: readonly SignalPoint[]): void {
  points.forEach(([time, value]) => {
    let row = rows.get(time)
    if (!row) {
      row = new Array<CsvValue>(width).fill(null)
      row[0] = time
      rows.set(time, row)
    }
    row[column] = value
  })
}

export interface CurveTable {
  /** `time_sec`, one column per metric (its label), then the smoothed primary metric. */
  columns: string[]
  /** One row per sample time, in time order; a cell is null where that series has no sample. */
  rows: CsvValue[][]
}

/** The curve as a table: the Data tab shows it and the CSV export writes it. */
export function curveTable(report: EngagementReport): CurveTable {
  const primary = report.metrics.find((metric) => metric.primary) ?? report.metrics[0]
  const columns = ['time_sec', ...report.metrics.map((metric) => metric.label), `${primary?.label ?? 'signal'} (smoothed)`]
  const rows = new Map<number, CsvValue[]>()
  report.metrics.forEach((metric, i) => setColumn(rows, columns.length, i + 1, metric.points))
  setColumn(rows, columns.length, columns.length - 1, report.smoothed)
  return { columns, rows: [...rows.values()].sort((a, b) => Number(a[0]) - Number(b[0])) }
}

export function curveCsv(report: EngagementReport): string {
  const table = curveTable(report)
  return toCsv(table.columns, table.rows)
}

const EXTREMA_COLUMNS = ['id', 'kind', 'time_sec', 'value', 'delta_pct', 'prominence', 'window_start_sec', 'window_end_sec', 'segment_id', 'title', 'explanation', 'drivers']

function extremumRow(e: ReportExtremum): CsvValue[] {
  return [e.id, e.kind, e.time_sec, e.value, e.delta_pct, e.prominence, e.window.start_sec, e.window.end_sec, e.segment_id, e.title, e.explanation, e.drivers.join('; ')]
}

/** Peaks, valleys and drops with their figures and prose. */
export function extremaCsv(report: EngagementReport): string {
  return toCsv(EXTREMA_COLUMNS, report.extrema.map(extremumRow))
}

const DRIVER_COLUMNS = ['key', 'name', 'kind', 'avg_during', 'delta_pct', 'coverage_sec', 'coverage_pct', 'low_support', 'ranges_sec']

function driverRow(d: ReportInfluence): CsvValue[] {
  const ranges = d.ranges.map((range) => `${range.start_sec}-${range.end_sec}`).join('; ')
  return [d.key, d.name, d.kind, d.avg_during, d.delta_pct, d.coverage_sec, d.coverage_pct, d.low_support, ranges]
}

/** Drivers: how the curve behaved while each character, object, location, emotion or event was present. */
export function driversCsv(report: EngagementReport): string {
  return toCsv(DRIVER_COLUMNS, report.influence.map(driverRow))
}
