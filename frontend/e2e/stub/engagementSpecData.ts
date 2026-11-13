/**
 * Fixture documents for the Engagement specs, read from the same JSON files
 * the stub serves, plus a sample-by-sample reference for averages so the
 * specs do not check the app against its own maths.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import type { EngagementReport, ReportExtremum, SignalPoint } from '../../src/types/insights.ts'

// Playwright loads spec files as CommonJS, so `__dirname` is available here (and `import.meta` is not).
const REPORTS_DIR = path.join(__dirname, 'data', 'engagement', 'reports')

function loadReport(name: string): EngagementReport {
  return JSON.parse(readFileSync(path.join(REPORTS_DIR, `${name}.json`), 'utf8')) as EngagementReport
}

/** Report of `eng-fixture-template` (jumpy template, with prose). */
export const TEMPLATE_REPORT = loadReport('template-jumpy')
/** Report of `eng-fixture-barc` (three metrics, TVR primary, smoothed differs from raw). */
export const BARC_REPORT = loadReport('barc')
/** Report of `eng-fixture-no-prose`. */
export const NO_PROSE_REPORT = loadReport('template-jumpy-no-prose')

export const TEMPLATE_ID = 'eng-fixture-template'
export const BARC_ID = 'eng-fixture-barc'
export const RUNNING_ID = 'eng-fixture-running'
export const WAITING_ID = 'eng-fixture-waiting'
export const FAILED_ID = 'eng-fixture-failed'
export const NO_PROSE_ID = 'eng-fixture-no-prose'

export function primaryPoints(report: EngagementReport): SignalPoint[] {
  return (report.metrics.find((metric) => metric.primary) ?? report.metrics[0]).points
}

export function extremum(report: EngagementReport, id: string): ReportExtremum {
  const found = report.extrema.find((item) => item.id === id)
  if (!found) throw new Error(`fixture report has no extremum ${id}`)
  return found
}

/** Value that holds at `timeSec`: the last sample at or before it. */
export function valueAt(points: readonly SignalPoint[], timeSec: number): number {
  let value = points[0][1]
  for (const [time, sample] of points) {
    if (time > timeSec) break
    value = sample
  }
  return value
}

/** Time-weighted mean over `[start, end)`, walking every sample (each holds for `interval`). */
export function meanBetween(points: readonly SignalPoint[], interval: number, start: number, end: number): number {
  let area = 0
  let cover = 0
  for (const [time, value] of points) {
    const overlap = Math.min(time + interval, end) - Math.max(time, start)
    if (overlap > 0) {
      area += value * overlap
      cover += overlap
    }
  }
  return area / cover
}

/** The app's fixed-decimal display of a signal value (2 decimals below 10, 1 below 1000). */
export function shown(value: number, unit = ''): string {
  const digits = Math.abs(value) >= 1000 ? 0 : Math.abs(value) >= 10 ? 1 : 2
  const text = value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return unit === '%' ? `${text}%` : text
}
