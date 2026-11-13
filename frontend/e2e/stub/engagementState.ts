/**
 * In-memory engagement records for the stub API (the Engagement twin of `state.ts`).
 *
 * Seed (restored by `reset()`, which must run after the scene analysis store's):
 *   eng-fixture-template   completed; jumpy template, report with prose
 *   eng-fixture-barc       completed; BARC CSV, three metrics
 *   eng-fixture-no-prose   completed; jumpy template, numbers only (both language-model steps failed)
 *   eng-fixture-failed     failed in `signal`; `retry()` requeues it and it then runs to completion
 *   eng-fixture-waiting    pending/waiting: its scene analysis (`sa-fixture-running`) is not done yet
 *   eng-fixture-running    a job in flight; moves one step on every poll
 * Records created through the API are `eng-stub-1`, `eng-stub-2`, ...
 *
 * Stage names, details, progress values and messages are the worker's
 * (`workers/insight_jobs/engagement_processor.py`). A job runs only once its
 * scene analysis is completed. Until then it is `pending` / `waiting`, and
 * each poll of it also moves that analysis one step, as if the scene worker
 * were running, so a waiting job finishes without anyone watching the analysis.
 */
import type {
  EngagementRecord,
  EngagementReport,
  EngagementSignalSpec,
  EngagementStatus,
  InsightUsage,
  SceneAnalysisRecord,
} from '../../src/types/insights.ts'
import { AD_SPOT_ID } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { TEXT_MODEL_CODE } from './data/catalog.ts'
import { BARC_CSV_FILENAME, NO_PROSE_REPORT, reportFor, signalNotes } from './data/engagement/documents.ts'
import { RUNNING_ID, sceneAnalysisStore, type SceneAnalysisStore } from './state.ts'

export const WAITING_STAGE = 'waiting'

// Messages and notes of the real worker, word for word.
const ANALYSIS_MISSING = 'The scene analysis this report was built on no longer exists. Start a new engagement analysis.'
const ANALYSIS_FAILED = 'The scene analysis of this video failed, so the report could not be built. Retry the scene analysis, then retry this report.'
const ANALYSIS_ARCHIVED = 'The scene analysis of this video was archived before it finished, so it will not complete. Start a new engagement analysis.'
const CSV_UNREADABLE = 'The signal CSV could not be downloaded. It may have been deleted from Files.'
const EXPLAIN_NOTE = 'Explanations could not be generated'
const RECOMMEND_NOTE = 'Recommendations could not be generated'

export interface EngagementStep {
  status: EngagementStatus
  stage: string
  stage_detail: string
  progress_pct: number
}

const step = (
  status: EngagementStatus,
  stage: string,
  stage_detail: string,
  progress_pct: number,
): EngagementStep => ({ status, stage, stage_detail, progress_pct })

const WAITING_STEP = step('pending', WAITING_STAGE, 'Waiting for scene analysis', 0)
/** From this step on the record knows the video's duration (the worker writes it with the statistics). */
const STATS_STEP = 2

function hasExplanations(report: EngagementReport): boolean {
  return report.extrema.length === 0 || report.extrema.some((e) => e.title !== '' || e.explanation !== '')
}

function hasRecommendations(report: EngagementReport): boolean {
  const { headline, do_more, do_less, segment_fixes } = report.recommendations
  return headline !== '' || do_more.length + do_less.length + segment_fixes.length > 0
}

/** What the worker joins into `stage_detail` on completion: parser warnings, then missing prose. */
function completionNotes(report: EngagementReport): string[] {
  const notes = [...signalNotes(report)]
  if (!hasExplanations(report)) notes.push(EXPLAIN_NOTE)
  if (!hasRecommendations(report)) notes.push(RECOMMEND_NOTE)
  return notes
}

/**
 * What a polling client sees for a job that serves `report`, one entry per
 * poll: 6 polls from queued to completed. Stages: signal → stats → explain → recommend.
 */
export function progressionFor(report: EngagementReport): readonly EngagementStep[] {
  const moments = report.extrema.length
  return [
    // The real backend leaves `stage` empty until a worker picks the job up, and again on completion.
    step('pending', '', '', 0),
    step('processing', 'signal', `${report.signal.point_count} samples`, 15),
    step('processing', 'stats', `${moments} moments found`, 30),
    step('processing', 'explain', `Explaining ${moments} moments`, 34),
    step('processing', 'recommend', 'Writing recommendations', 73),
    step('completed', '', completionNotes(report).join('; '), 100),
  ]
}

/** The signal of a template job, as the API stores it. */
export function templateSignal(templateId: string): EngagementSignalSpec {
  return { kind: 'template', template_id: templateId, upload_id: null, csv_filename: '', time_column: null, metric: null, offset_sec: 0 }
}

export interface CsvChoice {
  upload_id: string
  csv_filename: string
  time_column: string | null
  metric: string | null
  offset_sec: number
}

/** The signal of a BARC job, as the API stores it. */
export function barcSignal(csv: CsvChoice): EngagementSignalSpec {
  return { kind: 'barc', template_id: null, ...csv }
}

export interface NewEngagement {
  /** The scene analysis the job builds on; the video fields are copied from it. */
  analysis: SceneAnalysisRecord
  signal: EngagementSignalSpec
  display_name: string
}

type Phase = 'waiting' | 'running' | 'settled'

interface Entry {
  record: EngagementRecord
  /** The report this job serves once it is completed. */
  report: EngagementReport
  steps: readonly EngagementStep[]
  /** `waiting`: held back by its scene analysis. `running`: at `steps[step]`. `settled`: completed or failed. */
  phase: Phase
  step: number
  /** Insertion order; breaks `createdAt` ties when listing. */
  seq: number
}

interface Seed {
  id: string
  display_name: string
  analysis_id: string
  signal: EngagementSignalSpec
  createdAt: string
  /** Overrides the report chosen from the signal. */
  report?: EngagementReport
  /** Set for a job that has completed. */
  completedAt?: string
  /** Set for a job that failed while running. */
  failure?: { stage: string; error_message: string }
}

const SEEDS: readonly Seed[] = [
  {
    id: 'eng-fixture-template',
    display_name: 'Monsoon spot — Jumpy template',
    analysis_id: AD_SPOT_ID,
    signal: templateSignal('jumpy'),
    createdAt: '2026-11-12T10:05:00Z',
    completedAt: '2026-11-12T10:05:41Z',
  },
  {
    id: 'eng-fixture-barc',
    display_name: 'Monsoon spot — BARC ratings',
    analysis_id: AD_SPOT_ID,
    signal: barcSignal({ upload_id: 'upl-fixture-barc-csv', csv_filename: BARC_CSV_FILENAME, time_column: 'Start Time', metric: 'TVR (%)', offset_sec: -5 }),
    createdAt: '2026-11-12T11:20:00Z',
    completedAt: '2026-11-12T11:20:47Z',
  },
  {
    id: 'eng-fixture-no-prose',
    display_name: 'Monsoon spot — numbers only',
    analysis_id: AD_SPOT_ID,
    signal: templateSignal('jumpy'),
    report: NO_PROSE_REPORT,
    createdAt: '2026-11-12T14:10:00Z',
    completedAt: '2026-11-12T14:10:19Z',
  },
  {
    id: 'eng-fixture-failed',
    display_name: 'Monsoon spot — missing CSV',
    analysis_id: AD_SPOT_ID,
    // The upload behind this job is gone from the catalog, as the error says.
    signal: barcSignal({ upload_id: 'upl-fixture-deleted-csv', csv_filename: 'barc-week-28-evening.csv', time_column: null, metric: null, offset_sec: 0 }),
    createdAt: '2026-11-12T16:40:00Z',
    failure: { stage: 'signal', error_message: CSV_UNREADABLE },
  },
  {
    id: 'eng-fixture-waiting',
    display_name: 'Monsoon drama trailer — engagement',
    analysis_id: RUNNING_ID,
    signal: templateSignal('high'),
    createdAt: '2026-11-13T05:45:00Z',
  },
  {
    id: 'eng-fixture-running',
    display_name: 'Monsoon spot — in progress',
    analysis_id: AD_SPOT_ID,
    signal: templateSignal('slow_burn'),
    createdAt: '2026-11-13T06:15:00Z',
  },
]

const EMPTY_USAGE: InsightUsage = { input_tokens: 0, output_tokens: 0, model_name: TEXT_MODEL_CODE, cost_usd: 0 }
/** Two text calls (explain, recommend) at the catalog's token prices. */
const PROSE_USAGE: InsightUsage = { input_tokens: 5840, output_tokens: 1620, model_name: TEXT_MODEL_CODE, cost_usd: 0.0058 }
/** The same two calls when neither answer was usable: billed, but short. */
const NO_PROSE_USAGE: InsightUsage = { input_tokens: 5840, output_tokens: 310, model_name: TEXT_MODEL_CODE, cost_usd: 0.0025 }

/** A queued record with nothing computed yet. */
function blankRecord(id: string, input: NewEngagement, report: EngagementReport, createdAt: string): EngagementRecord {
  const { analysis } = input
  return {
    id,
    scene_analysis_id: analysis.id,
    source_type: analysis.source_type,
    source_id: analysis.source_id,
    video_gcs_uri: analysis.video_gcs_uri,
    video_filename: analysis.video_filename,
    display_name: input.display_name,
    mime_type: analysis.mime_type,
    signal: { ...input.signal },
    status: 'pending',
    stage: '',
    stage_detail: '',
    progress_pct: 0,
    error_message: null,
    duration_sec: 0,
    headline: '',
    kpis: {},
    schema_version: report.schema_version,
    usage: { ...EMPTY_USAGE },
    archived: false,
    createdAt,
    completedAt: null,
  }
}

/** Writes the fields the worker would have set by the time it reaches `entry.step`. */
function applyStep(entry: Entry): void {
  const { record, report, steps } = entry
  Object.assign(record, steps[entry.step])
  if (entry.step >= STATS_STEP) record.duration_sec = report.duration_sec
  if (entry.step < steps.length - 1) return
  record.headline = report.recommendations.headline
  record.kpis = structuredClone(report.kpis)
  record.usage = { ...(hasExplanations(report) && hasRecommendations(report) ? PROSE_USAGE : NO_PROSE_USAGE) }
  record.completedAt = new Date().toISOString()
}

/** Queues the job at the first step of its own progression. */
function start(entry: Entry): void {
  entry.phase = 'running'
  entry.step = 0
  applyStep(entry)
}

function hold(entry: Entry): void {
  entry.phase = 'waiting'
  Object.assign(entry.record, WAITING_STEP)
}

function fail(entry: Entry, stage: string, message: string): void {
  entry.phase = 'settled'
  Object.assign(entry.record, step('failed', stage, '', 0), { error_message: message })
}

/** The worker's `dependency_error`: why a job can never run on this analysis; null while it still can. */
function dependencyError(analysis: SceneAnalysisRecord | undefined): string | null {
  if (!analysis) return ANALYSIS_MISSING
  if (analysis.status === 'completed') return null
  if (analysis.status === 'failed') return ANALYSIS_FAILED
  return analysis.archived ? ANALYSIS_ARCHIVED : null
}

export class EngagementStore {
  private readonly entries = new Map<string, Entry>()
  private readonly analyses: SceneAnalysisStore
  private nextSeq = 0
  private created = 0

  constructor(analyses: SceneAnalysisStore) {
    this.analyses = analyses
    this.reset()
  }

  /** Restores the seed state. The seeds link to seeded scene analyses, so reset those first. */
  reset(): void {
    this.entries.clear()
    this.nextSeq = 0
    this.created = 0
    for (const seed of SEEDS) this.plant(seed)
  }

  private plant(seed: Seed): void {
    const analysis = this.analyses.get(seed.analysis_id)
    if (!analysis) throw new Error(`Engagement seed ${seed.id} needs scene analysis ${seed.analysis_id}; reset that store first`)
    const input: NewEngagement = { analysis, signal: seed.signal, display_name: seed.display_name }
    const entry = this.put(seed.id, input, seed.createdAt, seed.report ?? reportFor(seed.signal))
    if (seed.failure) fail(entry, seed.failure.stage, seed.failure.error_message)
    else if (seed.completedAt) this.run(entry, entry.steps.length)
    else this.admit(entry)
    if (seed.completedAt) entry.record.completedAt = seed.completedAt
  }

  private put(id: string, input: NewEngagement, createdAt: string, report: EngagementReport): Entry {
    const record = blankRecord(id, input, report, createdAt)
    const entry: Entry = { record, report, steps: progressionFor(report), phase: 'running', step: 0, seq: this.nextSeq++ }
    this.entries.set(id, entry)
    return entry
  }

  /** A queued job starts at once when its analysis is completed and waits otherwise. */
  private admit(entry: Entry): void {
    const analysis = this.analyses.get(entry.record.scene_analysis_id)
    if (analysis?.status === 'completed') start(entry)
    else hold(entry)
  }

  /** The worker's gate for a waiting job: fail it, start it, or leave it waiting. Returns the new phase. */
  private gate(entry: Entry): Phase {
    const analysis = this.analyses.get(entry.record.scene_analysis_id)
    const error = dependencyError(analysis)
    if (error) fail(entry, '', error)
    else if (analysis?.status === 'completed') start(entry)
    return entry.phase
  }

  private run(entry: Entry, steps: number): void {
    const last = entry.steps.length - 1
    entry.step = Math.min(last, entry.step + steps)
    applyStep(entry)
    if (entry.step === last) entry.phase = 'settled'
  }

  /** What happens between two polls: a running job moves one step, a waiting one drives its analysis. */
  private tick(entry: Entry): void {
    if (entry.phase === 'running') this.run(entry, 1)
    if (entry.phase !== 'waiting' || this.gate(entry) !== 'waiting') return
    this.analyses.advance(entry.record.scene_analysis_id, 1)
    this.gate(entry)
  }

  /** Newest first. Archived records are included only when asked for. */
  list(includeArchived: boolean): EngagementRecord[] {
    const visible = [...this.entries.values()].filter((e) => includeArchived || !e.record.archived)
    visible.sort((a, b) => b.record.createdAt.localeCompare(a.record.createdAt) || b.seq - a.seq)
    return visible.map((e) => structuredClone(e.record))
  }

  /** Current state, without moving the job. */
  get(id: string): EngagementRecord | undefined {
    const entry = this.entries.get(id)
    return entry ? structuredClone(entry.record) : undefined
  }

  /** The report of a job; the caller checks that the job is completed. */
  report(id: string): EngagementReport | undefined {
    return this.entries.get(id)?.report
  }

  /** Current state; the job then moves on (see `tick`), so the next poll sees progress. */
  poll(id: string): EngagementRecord | undefined {
    const entry = this.entries.get(id)
    if (!entry) return undefined
    const snapshot = structuredClone(entry.record)
    this.tick(entry)
    return snapshot
  }

  /**
   * Moves a running job forward by `steps` (stops at completed). A waiting job is
   * only re-checked against its analysis, which is never advanced from here: it
   * starts and moves if the analysis is completed, fails if the analysis cannot
   * complete, and stays waiting otherwise. Returns false for an unknown id.
   */
  advance(id: string, steps: number): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    if (entry.phase === 'waiting') this.gate(entry)
    if (entry.phase === 'running') this.run(entry, steps)
    return true
  }

  create(input: NewEngagement, report: EngagementReport = reportFor(input.signal)): EngagementRecord {
    this.created += 1
    const entry = this.put(`eng-stub-${this.created}`, input, new Date().toISOString(), report)
    this.admit(entry)
    return structuredClone(entry.record)
  }

  /** Requeues the job from the start. The caller checks that the record may be retried. */
  retry(id: string): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    entry.record.error_message = null
    this.admit(entry)
    return true
  }

  update(id: string, changes: Pick<Partial<EngagementRecord>, 'display_name' | 'archived'>): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    Object.assign(entry.record, changes)
    return true
  }

  delete(id: string): boolean {
    return this.entries.delete(id)
  }
}

/** The one engagement store; it reads (and, for waiting jobs, drives) the shared scene analysis store. */
export const engagementStore = new EngagementStore(sceneAnalysisStore)
