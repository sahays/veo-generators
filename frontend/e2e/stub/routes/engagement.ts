/**
 * Engagement routes (contract section 3), prefix `/api/v1/engagement`.
 * Status codes, `{detail}` texts and the order of the checks follow the real
 * FastAPI router (`api/routers/media/engagement.py` + `register_crud_routes`
 * + `signal_files.py`): shape problems are 422s, rule violations are 400s.
 *
 * Records live in `../engagementState.ts`, the report / template / preview
 * documents in `../data/engagement/`. `routes/sceneAnalysis.ts` is the sibling
 * to compare with when adding the next feature.
 */
import type {
  EngagementCreateResponse,
  EngagementRecord,
  EngagementSignalSpec,
  InsightSourceType,
  SceneAnalysisRecord,
} from '../../../src/types/insights.ts'
import { TEMPLATES, isTemplateId, previewFor } from '../data/engagement/documents.ts'
import { barcSignal, engagementStore as store, templateSignal } from '../engagementState.ts'
import type { StubFeature } from '../lib/feature.ts'
import { HttpError, isJsonObject, validationError, type JsonObject, type JsonValue } from '../lib/http.ts'
import { ok, route, type Reply, type Route, type RouteContext } from '../lib/router.ts'
import { BodyFields, ID_PATTERN, MODEL_PATTERN, isValidId } from '../lib/validate.ts'
import { VIDEO_FILE } from '../media.ts'
import { sceneAnalysisStore as analyses } from '../state.ts'
import { resolveSource } from './sceneAnalysis.ts'
import { sourceRoutes } from './sources.ts'
import { lookupUpload } from './uploads.ts'

const BASE = '/api/v1/engagement'
/** The real router's resource label is "Engagement report". */
const NOT_FOUND = 'Engagement report not found'
const CREATE_KEYS = ['scene_analysis_id', 'source_type', 'source_id', 'signal', 'display_name', 'model_id', 'region'] as const
const SIGNAL_KEYS = ['kind', 'template_id', 'upload_id', 'csv_filename', 'time_column', 'metric', 'offset_sec'] as const
const SIGNAL_KINDS = ['template', 'barc'] as const
const SOURCE_TYPES = ['upload', 'production'] as const
const DISPLAY_NAME_MAX = 200
const COLUMN_NAME_MAX = 200
const MAX_OFFSET_SEC = 86_400
const MAX_ADVANCE_STEPS = 20
const CSV_EXTENSIONS: ReadonlySet<string> = new Set(['.csv', '.tsv', '.txt'])
const CSV_MIME_TYPES: ReadonlySet<string> = new Set([
  'text/csv',
  'text/plain',
  'text/x-csv',
  'text/tab-separated-values',
  'application/csv',
])

/** The create payload after shape validation (422s); the rules between fields are checked later (400s). */
interface SignalInput {
  kind: (typeof SIGNAL_KINDS)[number]
  template_id?: string
  upload_id?: string
  time_column?: string
  metric?: string
  offset_sec: number
}

interface CreateInput {
  scene_analysis_id?: string
  source_type?: InsightSourceType
  source_id?: string
  signal: SignalInput
  display_name: string
  model_id: string | null
  region: string | null
}

/** A malformed id can never name a record, so it reads as not found (as on the real API). */
function recordId(ctx: RouteContext): string {
  const { id } = ctx.params
  if (!isValidId(id)) throw new HttpError(404, NOT_FOUND)
  return id
}

function found<T>(value: T | undefined | false): T {
  if (value === undefined || value === false) throw new HttpError(404, NOT_FOUND)
  return value
}

/** Like the real API's URL signing: every record response carries an absolute video URL. */
function signed(record: EngagementRecord, ctx: RouteContext): EngagementRecord {
  return { ...record, video_signed_url: ctx.mediaUrl(VIDEO_FILE) }
}

function list(ctx: RouteContext): Reply {
  const includeArchived = ctx.query.get('archived') === 'true'
  return ok(store.list(includeArchived).map((record) => signed(record, ctx)))
}

/** The polling endpoint: a job in flight moves one step after each read (see `EngagementStore.poll`). */
function get(ctx: RouteContext): Reply {
  return ok(signed(found(store.poll(recordId(ctx))), ctx))
}

async function patch(ctx: RouteContext): Promise<Reply> {
  const id = recordId(ctx)
  found(store.get(id))
  const name = (await ctx.body()).display_name
  if (typeof name !== 'string') throw new HttpError(400, 'No valid fields to update')
  store.update(id, { display_name: name.trim().slice(0, DISPLAY_NAME_MAX) })
  return ok({ status: 'updated' })
}

function remove(ctx: RouteContext): Reply {
  found(store.delete(recordId(ctx)))
  return ok({ status: 'deleted' })
}

const setArchived = (archived: boolean) => (ctx: RouteContext): Reply => {
  found(store.update(recordId(ctx), { archived }))
  return ok({ status: archived ? 'archived' : 'unarchived' })
}

function retry(ctx: RouteContext): Reply {
  const id = recordId(ctx)
  const record = found(store.get(id))
  if (record.status === 'pending' || record.status === 'completed') {
    throw new HttpError(400, `Cannot retry a ${record.status} engagement report`)
  }
  store.retry(id)
  return ok({ id, status: 'pending' })
}

/** `GET /sources/analyses`: the scene analyses a report can be built on, newest first. */
function analysisSources(ctx: RouteContext): Reply {
  const url = ctx.mediaUrl(VIDEO_FILE)
  const sources = analyses.list(false).map((a) => ({
    id: a.id,
    display_name: a.display_name ?? '',
    video_filename: a.video_filename,
    source_type: a.source_type,
    source_id: a.source_id,
    status: a.status,
    duration_sec: a.duration_sec,
    createdAt: a.createdAt,
    video_signed_url: url,
  }))
  return ok(sources)
}

/** As `looks_like_csv` in the real API: the name or the MIME type says "delimited text". */
function looksLikeCsv(filename: string, mimeType: string): boolean {
  const dot = filename.lastIndexOf('.')
  const extension = dot === -1 ? '' : filename.slice(dot).toLowerCase()
  const mime = mimeType.split(';')[0].trim().toLowerCase()
  return CSV_EXTENSIONS.has(extension) || CSV_MIME_TYPES.has(mime)
}

/** The uploaded CSV behind an upload id, or the real API's refusal (`resolve_signal_upload`). */
function signalFile(uploadId: string): { upload_id: string; filename: string } {
  const upload = lookupUpload(uploadId)
  if (!upload) throw new HttpError(404, 'Signal file not found')
  if (upload.status !== 'completed') throw new HttpError(400, 'Signal file upload is not complete')
  if (upload.file_type !== 'other' || !looksLikeCsv(upload.filename, upload.mime_type)) {
    throw new HttpError(400, 'Signal file must be a CSV file')
  }
  return { upload_id: upload.id, filename: upload.display_name || upload.filename }
}

/** `POST /signal-preview`: the preview is picked by the upload's filename; the bytes are never parsed. */
async function signalPreview(ctx: RouteContext): Promise<Reply> {
  const fields = new BodyFields(await ctx.body(), ['upload_id'])
  const uploadId = fields.text('upload_id', { required: true, max: 128, pattern: ID_PATTERN })
  fields.assertValid()
  return ok(previewFor(signalFile(uploadId ?? '').filename))
}

/** Moves a 422 entry from `body.<field>` to `body.<key>.<field>`. */
function relocate(issue: JsonValue, key: string): JsonValue {
  if (!isJsonObject(issue) || !Array.isArray(issue.loc)) return issue
  const [root, ...rest] = issue.loc
  return { ...issue, loc: [root, key, ...rest] }
}

/** Runs the validation of the nested `signal` object; its 422 entries are reported under `body.signal`. */
function underSignal<T>(validate: () => T): T {
  try {
    return validate()
  } catch (err) {
    if (!(err instanceof HttpError) || err.status !== 422 || !Array.isArray(err.detail)) throw err
    throw new HttpError(422, err.detail.map((issue) => relocate(issue, 'signal')))
  }
}

/** `offset_sec` is a plain number in the model (default 0); whether it is in range is a rule, checked later. */
function offsetOf(body: JsonObject): number {
  const value = body.offset_sec
  if (value === undefined) return 0
  if (typeof value !== 'number') throw validationError({ offset_sec: 'Input should be a valid number' })
  return value
}

function signalFields(body: JsonObject): SignalInput {
  const fields = new BodyFields(body, SIGNAL_KEYS)
  const kind = fields.choice('kind', SIGNAL_KINDS)
  const templateId = fields.text('template_id', { max: 64, pattern: ID_PATTERN })
  const uploadId = fields.text('upload_id', { max: 128, pattern: ID_PATTERN })
  // Part of the client's signal type, so accepted; the stored name always comes from the upload.
  fields.text('csv_filename', { max: 300 })
  const timeColumn = fields.text('time_column', { max: COLUMN_NAME_MAX })
  const metric = fields.text('metric', { max: COLUMN_NAME_MAX })
  fields.assertValid()
  if (!kind) throw validationError({ kind: 'Field required' })
  return { kind, template_id: templateId, upload_id: uploadId, time_column: timeColumn, metric, offset_sec: offsetOf(body) }
}

function parseSignal(value: JsonValue | undefined): SignalInput {
  if (value === undefined || value === null) throw validationError({ signal: 'Field required' })
  if (!isJsonObject(value)) throw validationError({ signal: 'Input should be a valid dictionary or object' })
  return underSignal(() => signalFields(value))
}

function parseCreate(body: JsonObject): CreateInput {
  const fields = new BodyFields(body, CREATE_KEYS)
  const analysisId = fields.text('scene_analysis_id', { max: 128, pattern: ID_PATTERN })
  const hasSourceType = body.source_type !== undefined && body.source_type !== null
  const sourceType = hasSourceType ? fields.choice('source_type', SOURCE_TYPES) : undefined
  const sourceId = fields.text('source_id', { max: 128, pattern: ID_PATTERN })
  const displayName = fields.text('display_name', { max: DISPLAY_NAME_MAX })
  const modelId = fields.text('model_id', { max: 100, pattern: MODEL_PATTERN })
  const region = fields.text('region', { max: 64, pattern: MODEL_PATTERN })
  fields.assertValid()
  return {
    scene_analysis_id: analysisId,
    source_type: sourceType,
    source_id: sourceId,
    signal: parseSignal(body.signal),
    display_name: (displayName ?? '').trim(),
    model_id: modelId ?? null,
    region: region ?? null,
  }
}

/** Exactly one video reference: an analysis id, or a source type + id. */
function checkReferences(input: CreateInput): void {
  const bySource = Boolean(input.source_type && input.source_id)
  const partialSource = Boolean(input.source_type || input.source_id) && !bySource
  if (partialSource || Boolean(input.scene_analysis_id) === bySource) {
    throw new HttpError(400, 'Provide either scene_analysis_id, or source_type with source_id')
  }
}

/** Rules that depend on the signal kind; nothing is looked up yet. */
function checkSignal(signal: SignalInput): void {
  if (signal.kind === 'template' && !isTemplateId(signal.template_id ?? '')) {
    throw new HttpError(400, 'Unknown engagement template')
  }
  if (signal.kind === 'barc' && !signal.upload_id) throw new HttpError(400, 'A BARC signal needs upload_id')
  if (!Number.isFinite(signal.offset_sec) || Math.abs(signal.offset_sec) > MAX_OFFSET_SEC) {
    throw new HttpError(400, `offset_sec must be within ${MAX_OFFSET_SEC} seconds of zero`)
  }
}

/** The signal as stored: only the fields its kind uses, the CSV resolved from the upload id. */
function storedSignal(signal: SignalInput): EngagementSignalSpec {
  if (signal.kind === 'template') return templateSignal(signal.template_id ?? '')
  const file = signalFile(signal.upload_id ?? '')
  return barcSignal({
    upload_id: file.upload_id,
    csv_filename: file.filename,
    time_column: signal.time_column?.trim() || null,
    metric: signal.metric?.trim() || null,
    offset_sec: signal.offset_sec,
  })
}

/** A scene analysis the client chose; it must still be able to complete. */
function existingAnalysis(id: string): SceneAnalysisRecord {
  const analysis = analyses.get(id)
  if (!analysis) throw new HttpError(404, 'Scene analysis not found')
  if (analysis.archived) throw new HttpError(400, 'Scene analysis is archived')
  if (analysis.status === 'failed') throw new HttpError(400, 'Scene analysis failed; retry it or choose another video')
  return analysis
}

/** The newest live analysis of a source (not archived, not failed), or a newly queued one. */
function analysisOfSource(sourceType: InsightSourceType, sourceId: string, input: CreateInput): SceneAnalysisRecord {
  const video = resolveSource(sourceType, sourceId)
  const reusable = analyses
    .list(false)
    .find((a) => a.source_type === sourceType && a.source_id === sourceId && a.status !== 'failed')
  if (reusable) return reusable
  return analyses.create({
    source_type: sourceType,
    source_id: sourceId,
    ...video,
    display_name: '',
    focus: '',
    model_id: input.model_id,
    region: input.region,
  })
}

/** The analysis to build on: the chosen one, a live one of the same source, or a new one. */
function analysisFor(input: CreateInput): SceneAnalysisRecord {
  if (input.scene_analysis_id) return existingAnalysis(input.scene_analysis_id)
  if (!input.source_type || !input.source_id) throw new HttpError(400, 'Provide either scene_analysis_id, or source_type with source_id')
  return analysisOfSource(input.source_type, input.source_id, input)
}

async function create(ctx: RouteContext): Promise<Reply> {
  const input = parseCreate(await ctx.body())
  checkReferences(input)
  checkSignal(input.signal)
  // The signal is resolved first: a bad CSV must not leave a new analysis behind.
  const signal = storedSignal(input.signal)
  const analysis = analysisFor(input)
  const record = store.create({ analysis, signal, display_name: input.display_name })
  const body: EngagementCreateResponse = { id: record.id, status: record.status, scene_analysis_id: analysis.id }
  return ok(body)
}

function report(ctx: RouteContext): Reply {
  const id = recordId(ctx)
  const record = found(store.get(id))
  if (record.status !== 'completed') throw new HttpError(409, 'Engagement report is not ready')
  return ok(found(store.report(id)))
}

/**
 * Test helper: `POST /__stub/engagement/{id}/advance` with optional `{"steps": n}` (default 1).
 * Moves the engagement job only; a job waiting on its scene analysis stays waiting.
 */
async function advance(ctx: RouteContext): Promise<Reply> {
  const id = recordId(ctx)
  const steps = (await ctx.body()).steps ?? 1
  if (typeof steps !== 'number' || !Number.isInteger(steps) || steps < 1 || steps > MAX_ADVANCE_STEPS) {
    throw new HttpError(400, `steps must be an integer between 1 and ${MAX_ADVANCE_STEPS}`)
  }
  found(store.advance(id, steps))
  return ok(signed(found(store.get(id)), ctx))
}

const routes: Route[] = [
  route('GET', BASE, list),
  route('POST', BASE, create),
  ...sourceRoutes(BASE),
  route('GET', `${BASE}/sources/analyses`, analysisSources),
  route('GET', `${BASE}/templates`, () => ok(TEMPLATES)),
  route('POST', `${BASE}/signal-preview`, signalPreview),
  route('GET', `${BASE}/{id}`, get),
  route('PATCH', `${BASE}/{id}`, patch),
  route('DELETE', `${BASE}/{id}`, remove),
  route('POST', `${BASE}/{id}/archive`, setArchived(true)),
  route('POST', `${BASE}/{id}/unarchive`, setArchived(false)),
  route('POST', `${BASE}/{id}/retry`, retry),
  route('GET', `${BASE}/{id}/report`, report),
  route('POST', '/__stub/engagement/{id}/advance', advance),
]

export const engagementFeature: StubFeature = {
  name: 'engagement',
  routes,
  reset: () => store.reset(),
  usage: (id) => store.get(id)?.usage,
}
