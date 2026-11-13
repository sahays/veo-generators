/**
 * In-memory scene analysis records for the stub API.
 *
 * Seed (restored by `reset()`):
 *   sa-fixture-ad-spot   completed; the `AD_SPOT_RECORD` fixture
 *   sa-fixture-running   a job in flight; moves one step through `PROGRESSION` on every poll
 *   sa-fixture-failed    failed in `analyze`; `retry()` requeues it and it then runs like the one above
 * Records created through the API also run through `PROGRESSION`.
 *
 * Every job that completes here serves the same fixture timeline (`AD_SPOT_TIMELINE`).
 */
import type {
  InsightSourceType,
  InsightUsage,
  SceneAnalysisRecord,
  SceneAnalysisStatus,
} from '../../src/types/insights.ts'
import {
  AD_SPOT_ID,
  AD_SPOT_RECORD,
  AD_SPOT_TIMELINE,
} from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { DEFAULT_REGION, TEXT_MODEL_CODE } from './data/catalog.ts'

export const RUNNING_ID = 'sa-fixture-running'
export const FAILED_ID = 'sa-fixture-failed'
export const SEEDED_IDS: readonly string[] = [AD_SPOT_ID, RUNNING_ID, FAILED_ID]

const WINDOW_COUNT = 3

export interface ProgressStep {
  status: SceneAnalysisStatus
  stage: string
  stage_detail: string
  progress_pct: number
}

const step = (
  status: SceneAnalysisStatus,
  stage: string,
  stage_detail: string,
  progress_pct: number,
): ProgressStep => ({ status, stage, stage_detail, progress_pct })

/**
 * What a polling client sees, one entry per poll: 8 polls from queued to completed.
 * Stages follow the worker contract: probe → analyze (per window) → merge → filmstrip.
 */
export const PROGRESSION: readonly ProgressStep[] = [
  // The real backend leaves `stage` empty until a worker picks the job up.
  step('pending', '', '', 0),
  step('analyzing', 'probe', 'Reading the video and detecting cuts', 5),
  step('analyzing', 'analyze', `window 1 of ${WINDOW_COUNT}`, 25),
  step('analyzing', 'analyze', `window 2 of ${WINDOW_COUNT}`, 45),
  step('analyzing', 'analyze', `window 3 of ${WINDOW_COUNT}`, 70),
  step('processing', 'merge', `Merging ${WINDOW_COUNT} windows`, 85),
  step('processing', 'filmstrip', 'Building the filmstrip', 95),
  step('completed', 'completed', '', 100),
]

const LAST_STEP = PROGRESSION.length - 1
const PROBE_STEP = 1

export interface NewAnalysis {
  source_type: InsightSourceType
  source_id: string
  video_gcs_uri: string
  video_filename: string
  display_name: string
  focus: string
  model_id: string | null
  region: string | null
}

interface Entry {
  record: SceneAnalysisRecord
  /** Index into `PROGRESSION`, or null for a record that does not move (completed or failed). */
  step: number | null
  /** Insertion order; breaks `createdAt` ties when listing. */
  seq: number
}

const EMPTY_USAGE: InsightUsage = {
  input_tokens: 0,
  output_tokens: 0,
  model_name: TEXT_MODEL_CODE,
  cost_usd: 0,
}

/** A queued record with nothing analysed yet. */
function blankRecord(id: string, input: NewAnalysis, createdAt: string): SceneAnalysisRecord {
  return {
    id,
    ...input,
    mime_type: 'video/mp4',
    ...PROGRESSION[0],
    error_message: null,
    duration_sec: 0,
    window_count: 0,
    summary: '',
    content_title: '',
    counts: {},
    filmstrip: null,
    schema_version: AD_SPOT_RECORD.schema_version,
    usage: { ...EMPTY_USAGE },
    archived: false,
    createdAt,
    completedAt: null,
  }
}

/** Writes the fields the worker would have set by the time it reaches `index`. */
function applyStep(record: SceneAnalysisRecord, index: number): void {
  Object.assign(record, PROGRESSION[index])
  if (index >= PROBE_STEP) {
    record.duration_sec = AD_SPOT_TIMELINE.duration_sec
    record.window_count = WINDOW_COUNT
  }
  if (index < LAST_STEP) return
  record.summary = AD_SPOT_RECORD.summary
  record.content_title = AD_SPOT_RECORD.content_title
  record.counts = { ...AD_SPOT_RECORD.counts }
  record.filmstrip = AD_SPOT_RECORD.filmstrip ? { ...AD_SPOT_RECORD.filmstrip } : null
  record.usage = { ...AD_SPOT_RECORD.usage }
  record.completedAt = new Date().toISOString()
}

function seedCompleted(): SceneAnalysisRecord {
  const record = structuredClone(AD_SPOT_RECORD)
  // The fixture carries a relative placeholder; routes attach the absolute media URL.
  delete record.video_signed_url
  return record
}

function seedRunning(): SceneAnalysisRecord {
  const input: NewAnalysis = {
    source_type: 'upload',
    source_id: 'upl-fixture-trailer',
    video_gcs_uri: 'gs://fixture-bucket/uploads/monsoon-drama-trailer.mp4',
    video_filename: 'monsoon-drama-trailer.mp4',
    display_name: 'Monsoon drama trailer',
    focus: '',
    model_id: TEXT_MODEL_CODE,
    region: DEFAULT_REGION,
  }
  return blankRecord(RUNNING_ID, input, '2026-11-13T05:40:00Z')
}

function seedFailed(): SceneAnalysisRecord {
  const input: NewAnalysis = {
    source_type: 'production',
    source_id: 'prod-fixture-festive-teaser',
    video_gcs_uri: 'gs://fixture-bucket/productions/prod-fixture-festive-teaser/final.mp4',
    video_filename: 'Festive offer teaser.mp4',
    display_name: 'Festive offer teaser',
    focus: 'Offer callouts and price mentions',
    model_id: TEXT_MODEL_CODE,
    region: DEFAULT_REGION,
  }
  const record = blankRecord(FAILED_ID, input, '2026-11-12T18:05:00Z')
  applyStep(record, 3)
  record.status = 'failed'
  record.error_message = 'The model returned an unreadable response for window 2 of 3. Retry to resume from the last checkpoint.'
  return record
}

export class SceneAnalysisStore {
  private readonly entries = new Map<string, Entry>()
  private nextSeq = 0
  private created = 0

  constructor() {
    this.reset()
  }

  /** Restores the seed state. */
  reset(): void {
    this.entries.clear()
    this.nextSeq = 0
    this.created = 0
    this.put(seedCompleted(), null)
    this.put(seedFailed(), null)
    this.put(seedRunning(), 0)
  }

  private put(record: SceneAnalysisRecord, stepIndex: number | null): void {
    this.entries.set(record.id, { record, step: stepIndex, seq: this.nextSeq++ })
  }

  /** Newest first. Archived records are included only when asked for. */
  list(includeArchived: boolean): SceneAnalysisRecord[] {
    const visible = [...this.entries.values()].filter((e) => includeArchived || !e.record.archived)
    visible.sort((a, b) => b.record.createdAt.localeCompare(a.record.createdAt) || b.seq - a.seq)
    return visible.map((e) => structuredClone(e.record))
  }

  /** Current state, without moving the job. */
  get(id: string): SceneAnalysisRecord | undefined {
    const entry = this.entries.get(id)
    return entry ? structuredClone(entry.record) : undefined
  }

  /** Current state; a job in flight then moves one step, so the next poll sees progress. */
  poll(id: string): SceneAnalysisRecord | undefined {
    const snapshot = this.get(id)
    if (snapshot) this.advance(id, 1)
    return snapshot
  }

  /** Moves a job in flight forward by `steps` (stops at completed). Returns false for an unknown id. */
  advance(id: string, steps: number): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    if (entry.step === null) return true
    entry.step = Math.min(LAST_STEP, entry.step + steps)
    applyStep(entry.record, entry.step)
    if (entry.step === LAST_STEP) entry.step = null
    return true
  }

  create(input: NewAnalysis): SceneAnalysisRecord {
    this.created += 1
    const record = blankRecord(`sa-stub-${this.created}`, input, new Date().toISOString())
    this.put(record, 0)
    return structuredClone(record)
  }

  /** Requeues the job from the start. The caller checks that the record may be retried. */
  retry(id: string): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    entry.record.error_message = null
    entry.step = 0
    applyStep(entry.record, 0)
    return true
  }

  update(id: string, changes: Pick<Partial<SceneAnalysisRecord>, 'display_name' | 'archived'>): boolean {
    const entry = this.entries.get(id)
    if (!entry) return false
    Object.assign(entry.record, changes)
    return true
  }

  delete(id: string): boolean {
    return this.entries.delete(id)
  }
}

/** The one store shared by every route module (Engagement links to these records). */
export const sceneAnalysisStore = new SceneAnalysisStore()
