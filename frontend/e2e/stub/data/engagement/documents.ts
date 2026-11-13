/**
 * The Engagement fixture documents, loaded once at startup from the JSON files
 * that `generate_fixtures.py` writes next to this module. Every number in them
 * comes from the real engagement maths (`api/engagement_signals`); only the
 * prose in `prose.json` is hand-written. Never edit the JSON by hand: regenerate.
 */
import { readFileSync } from 'node:fs'
import type {
  EngagementReport,
  EngagementSignalSpec,
  EngagementTemplate,
  SignalPreview,
} from '../../../../src/types/insights.ts'

function readJson<T>(relativePath: string): T {
  return JSON.parse(readFileSync(new URL(relativePath, import.meta.url), 'utf8')) as T
}

/** A JSON object as a Map, so that a looked-up name can never reach `Object.prototype`. */
function readJsonMap<T>(relativePath: string): ReadonlyMap<string, T> {
  return new Map(Object.entries(readJson<Record<string, T>>(relativePath)))
}

/** The CSV behind `reports/barc.json`; also the filename of the catalog upload `upl-fixture-barc-csv`. */
export const BARC_CSV_FILENAME = 'barc-kadak-chai-monsoon.csv'

/** `GET /engagement/templates`. */
export const TEMPLATES: readonly EngagementTemplate[] = readJson('./templates.json')

const TEMPLATE_REPORTS: ReadonlyMap<string, EngagementReport> = new Map(
  TEMPLATES.map((t) => [t.id, readJson<EngagementReport>(`./reports/template-${t.id}.json`)]),
)

export const isTemplateId = (id: string): boolean => TEMPLATE_REPORTS.has(id)

/** The measured report: the BARC CSV, TVR as the primary metric, offset -5 s. */
export const BARC_REPORT: EngagementReport = readJson('./reports/barc.json')

/** The jumpy template report as the backend saves it when both language-model steps fail. */
export const NO_PROSE_REPORT: EngagementReport = readJson('./reports/template-jumpy-no-prose.json')

/** Parser warnings the worker notes on the record, by signal kind (`signal-notes.json`). */
const SIGNAL_NOTES = readJsonMap<readonly string[]>('./signal-notes.json')

/** `SignalPreview` by CSV filename (`previews.json`). */
const PREVIEWS = readJsonMap<SignalPreview>('./previews.json')

/**
 * The report a job with this signal serves once completed. Every BARC job gets
 * the one BARC report, whatever metric, time column or offset it asked for.
 */
export function reportFor(signal: EngagementSignalSpec): EngagementReport {
  const template = signal.kind === 'template' ? TEMPLATE_REPORTS.get(signal.template_id ?? '') : undefined
  return template ?? BARC_REPORT
}

/** Warnings from parsing the signal, as the worker would add them to the record's notes. */
export function signalNotes(report: EngagementReport): readonly string[] {
  return SIGNAL_NOTES.get(report.signal.kind) ?? []
}

/**
 * The preview of an uploaded CSV, chosen by filename: a file named in
 * `previews.json` gets its own preview, any other CSV gets the BARC preview
 * under its own name (the stub never parses the uploaded bytes).
 */
export function previewFor(filename: string): SignalPreview {
  const own = PREVIEWS.get(filename)
  if (own) return structuredClone(own)
  const barc = PREVIEWS.get(BARC_CSV_FILENAME)
  if (!barc) throw new Error(`previews.json has no entry for ${BARC_CSV_FILENAME}; regenerate the fixtures`)
  return { ...structuredClone(barc), filename }
}
