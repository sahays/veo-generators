import type { EngagementRecord, EngagementSignalSpec, ReportSignalMeta } from '@/types/insights'
import { categoryLabel } from '@/types/timeline/glyphs'

/** Label shown wherever a template curve, or a number derived from it, appears. */
export const SIMULATED_LABEL = 'Template (simulated)'
export const BARC_LABEL = 'BARC'
const NO_VALUE = '—'
const MINUS = '\u2212'

function fractionDigits(magnitude: number): number {
  if (magnitude >= 1000) return 0
  return magnitude >= 10 ? 1 : 2
}

/**
 * A signal value for display: thousands separators and a fixed number of
 * decimals for its size (`1.40`, `63.1`, `3,166`), so a column of readings
 * does not jitter; `%` is appended when that is the unit.
 */
export function formatValue(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_VALUE
  const digits = fractionDigits(Math.abs(value))
  const text = value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return unit === '%' ? `${text}%` : text
}

/** A value for an axis tick: as short as possible (`0`, `0.6`, `25`, `1,200`). */
export function formatAxisValue(value: number): string {
  return value.toLocaleString('en-US', { maximumFractionDigits: fractionDigits(Math.abs(value)) })
}

/** Signed percentage against the average: `+12.3%`, `−4.1%`, `0%`. */
export function formatDelta(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return NO_VALUE
  const rounded = Math.round(pct * 10) / 10
  if (rounded === 0) return '0%'
  const magnitude = Math.abs(rounded) >= 100 ? Math.round(Math.abs(rounded)) : Math.abs(rounded)
  return `${rounded > 0 ? '+' : MINUS}${magnitude}%`
}

/** Spoken form of a delta, for accessible names: "12.3% above average". */
export function describeDelta(pct: number): string {
  const rounded = Math.round(pct * 10) / 10
  if (rounded === 0) return 'at the average'
  return `${Math.abs(rounded)}% ${rounded > 0 ? 'above' : 'below'} average`
}

export interface SignalBadgeText {
  /** True for template curves: illustrative, not measured. */
  simulated: boolean
  /** "Template (simulated)" or "BARC". */
  kind: string
  /** The template's label, or the CSV file name. */
  detail: string
}

/** Badge text for a record's signal. `templateLabels` maps template ids to their labels. */
export function signalBadgeText(signal: EngagementSignalSpec, templateLabels: ReadonlyMap<string, string>): SignalBadgeText {
  if (signal.kind === 'barc') return { simulated: false, kind: BARC_LABEL, detail: signal.csv_filename ?? '' }
  const id = signal.template_id ?? ''
  return { simulated: true, kind: SIMULATED_LABEL, detail: templateLabels.get(id) ?? categoryLabel(id) }
}

/** Badge text for a completed report (its `label` is the template label or the CSV file name). */
export function reportBadgeText(signal: ReportSignalMeta): SignalBadgeText {
  return { simulated: signal.simulated, kind: signal.simulated ? SIMULATED_LABEL : BARC_LABEL, detail: signal.label }
}

/** Name shown for a record: the user's name, else the file name. */
export function engagementRecordName(record: Pick<EngagementRecord, 'display_name' | 'video_filename'>): string {
  return record.display_name || record.video_filename || 'Untitled video'
}

/**
 * Display name of a driver. Emotion names and event tags are schema keys
 * (`call_to_action`), so they are humanised; entity names are used as written.
 */
export function driverLabel(driver: { name: string; kind: string }): string {
  return driver.kind === 'emotion' || driver.kind === 'event' ? categoryLabel(driver.name) : driver.name
}
