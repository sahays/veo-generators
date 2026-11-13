import type { TimelineCue, TimelineDoc } from '@/types/insights'
import { formatSubtitleTime } from './timeFormat'

/** Shortest subtitle the exporters will write, so players never get a zero-length cue. */
const MIN_CUE_SEC = 0.05

export type CsvValue = string | number | boolean | null | undefined

/** Cues that carry spoken or described content; silence has nothing to show. */
function subtitleCues(cues: readonly TimelineCue[]): TimelineCue[] {
  return cues.filter((cue) => cue.kind !== 'silence' && cue.text.trim().length > 0)
}

/** One-paragraph cue body: blank lines would end the cue block in SRT and VTT. */
function flattenText(text: string): string {
  return text.replace(/\r/g, '').split('\n').map((line) => line.trim()).filter(Boolean).join('\n')
}

function cueWindow(cue: TimelineCue, separator: ',' | '.'): string {
  const end = Math.max(cue.end_sec, cue.start_sec + MIN_CUE_SEC)
  return `${formatSubtitleTime(cue.start_sec, separator)} --> ${formatSubtitleTime(end, separator)}`
}

function srtBody(cue: TimelineCue): string {
  const text = flattenText(cue.text)
  if (cue.kind === 'music' || cue.kind === 'sfx') return `[${text}]`
  return cue.speaker ? `${cue.speaker.trim()}: ${text}` : text
}

/** SubRip document from cues. */
export function cuesToSrt(cues: readonly TimelineCue[]): string {
  return subtitleCues(cues)
    .map((cue, i) => `${i + 1}\n${cueWindow(cue, ',')}\n${srtBody(cue)}\n`)
    .join('\n')
}

/** WebVTT cue text may not contain raw markup characters or the cue arrow. */
function escapeVtt(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function vttBody(cue: TimelineCue): string {
  const text = escapeVtt(flattenText(cue.text))
  if (cue.kind === 'music' || cue.kind === 'sfx') return `[${text}]`
  const speaker = cue.speaker ? escapeVtt(cue.speaker.trim()).replace(/\s+/g, ' ') : ''
  return speaker ? `<v ${speaker}>${text}` : text
}

/** WebVTT document from cues, with speakers as voice spans. */
export function cuesToVtt(cues: readonly TimelineCue[]): string {
  const blocks = subtitleCues(cues).map((cue) => `${cue.id}\n${cueWindow(cue, '.')}\n${vttBody(cue)}\n`)
  return ['WEBVTT\n', ...blocks].join('\n')
}

/**
 * One CSV cell. Text that a spreadsheet would evaluate as a formula (leading
 * `=`, `+`, `-`, `@`, tab or carriage return, optionally after spaces) is
 * neutralised with a leading apostrophe (OWASP CSV injection guidance).
 * Numbers and booleans are written as-is: `-3.2` stays a number.
 */
export function escapeCsvCell(value: CsvValue): string {
  if (value === null || value === undefined) return ''
  if (typeof value !== 'string') return String(value)
  const guarded = /^[\t\r]|^\s*[=+\-@]/.test(value) ? `'${value}` : value
  return /[",\n\r]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded
}

/** RFC 4180 CSV with CRLF line ends. */
export function toCsv(columns: readonly string[], rows: readonly (readonly CsvValue[])[]): string {
  const lines = [columns, ...rows].map((row) => row.map(escapeCsvCell).join(','))
  return `${lines.join('\r\n')}\r\n`
}

export type TimelineCollectionKey =
  | 'segments'
  | 'cues'
  | 'entities'
  | 'events'
  | 'emotions'
  | 'key_moments'
  | 'narrative_beats'

interface CollectionCsvSpec {
  label: string
  columns: string[]
  rows: (doc: TimelineDoc) => CsvValue[][]
}

/** Entities export one row per appearance so every on-screen range is kept. */
function entityRows(doc: TimelineDoc): CsvValue[][] {
  return doc.entities.flatMap((e) =>
    e.appearances.map((a) => [e.id, e.name, e.kind, e.description, e.screen_time_sec, a.start_sec, a.end_sec]),
  )
}

export const TIMELINE_CSV_SPECS: Record<TimelineCollectionKey, CollectionCsvSpec> = {
  segments: {
    label: 'Segments',
    columns: ['id', 'start_sec', 'end_sec', 'title', 'synopsis', 'location'],
    rows: (doc) => doc.segments.map((s) => [s.id, s.start_sec, s.end_sec, s.title, s.synopsis, s.location]),
  },
  cues: {
    label: 'Cues',
    columns: ['id', 'start_sec', 'end_sec', 'kind', 'speaker', 'sentiment', 'text'],
    rows: (doc) => doc.cues.map((c) => [c.id, c.start_sec, c.end_sec, c.kind, c.speaker, c.sentiment, c.text]),
  },
  entities: {
    label: 'Entities',
    columns: ['id', 'name', 'kind', 'description', 'screen_time_sec', 'appearance_start_sec', 'appearance_end_sec'],
    rows: entityRows,
  },
  events: {
    label: 'Events',
    columns: ['id', 'start_sec', 'end_sec', 'tag', 'intensity', 'description'],
    rows: (doc) => doc.events.map((e) => [e.id, e.start_sec, e.end_sec, e.tag, e.intensity, e.description]),
  },
  emotions: {
    label: 'Emotions',
    columns: ['id', 'start_sec', 'end_sec', 'emotion', 'intensity'],
    rows: (doc) => doc.emotions.map((e) => [e.id, e.start_sec, e.end_sec, e.emotion, e.intensity]),
  },
  key_moments: {
    label: 'Key moments',
    columns: ['id', 'start_sec', 'type', 'label'],
    rows: (doc) => doc.key_moments.map((m) => [m.id, m.start_sec, m.type, m.label]),
  },
  narrative_beats: {
    label: 'Narrative beats',
    columns: ['id', 'start_sec', 'end_sec', 'beat', 'label'],
    rows: (doc) => doc.narrative_beats.map((b) => [b.id, b.start_sec, b.end_sec, b.beat, b.label]),
  },
}

export const TIMELINE_COLLECTION_KEYS = Object.keys(TIMELINE_CSV_SPECS) as TimelineCollectionKey[]

export function timelineCollectionCsv(doc: TimelineDoc, key: TimelineCollectionKey): string {
  const spec = TIMELINE_CSV_SPECS[key]
  return toCsv(spec.columns, spec.rows(doc))
}

/** File-system safe stem for export file names. */
export function exportFileStem(name: string): string {
  const stem = name.trim().replace(/\.[a-z0-9]{2,4}$/i, '').replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '')
  return stem.toLowerCase() || 'timeline'
}
