/**
 * Scene analysis routes (contract section 3), prefix `/api/v1/scene-analysis`.
 * Response bodies and status codes follow the real FastAPI router
 * (`api/routers/media/scene_analysis.py` + `register_crud_routes`).
 */
import type { SceneAnalysisRecord, TimelineResponse } from '../../../src/types/insights.ts'
import {
  AD_SPOT_FILMSTRIP,
  AD_SPOT_TIMELINE,
} from '../../../src/types/timeline/__tests__/adSpotFixture.ts'
import { findProduction, findVideoUpload } from '../data/catalog.ts'
import type { StubFeature } from '../lib/feature.ts'
import { HttpError } from '../lib/http.ts'
import { ok, route, type Reply, type Route, type RouteContext } from '../lib/router.ts'
import { BodyFields, ID_PATTERN, MODEL_PATTERN, isValidId } from '../lib/validate.ts'
import { FILMSTRIP_FILE, VIDEO_FILE } from '../media.ts'
import { sceneAnalysisStore as store, type NewAnalysis } from '../state.ts'
import { sourceRoutes } from './sources.ts'

const BASE = '/api/v1/scene-analysis'
const NOT_FOUND = 'Scene analysis not found'
const CREATE_KEYS = ['source_type', 'source_id', 'focus', 'display_name', 'model_id', 'region'] as const
const DISPLAY_NAME_MAX = 200
const MAX_ADVANCE_STEPS = 20

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
function signed(record: SceneAnalysisRecord, ctx: RouteContext): SceneAnalysisRecord {
  return { ...record, video_signed_url: ctx.mediaUrl(VIDEO_FILE) }
}

function list(ctx: RouteContext): Reply {
  const includeArchived = ctx.query.get('archived') === 'true'
  return ok(store.list(includeArchived).map((record) => signed(record, ctx)))
}

/** The polling endpoint: a job in flight moves one step after each read. */
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
    throw new HttpError(400, `Cannot retry a ${record.status} scene analysis`)
  }
  store.retry(id)
  return ok({ id, status: 'pending' })
}

/** Resolves the picked source to its video, as the server does; the client never sends a URI. */
export function resolveSource(sourceType: 'upload' | 'production', sourceId: string): Pick<NewAnalysis, 'video_gcs_uri' | 'video_filename'> {
  if (sourceType === 'upload') {
    const upload = findVideoUpload(sourceId)
    if (!upload) throw new HttpError(404, 'Upload not found')
    return { video_gcs_uri: upload.gcs_uri, video_filename: upload.filename }
  }
  const production = findProduction(sourceId)
  if (!production) throw new HttpError(404, 'Production not found')
  return { video_gcs_uri: production.final_video_url, video_filename: `${production.name}.mp4` }
}

async function create(ctx: RouteContext): Promise<Reply> {
  const fields = new BodyFields(await ctx.body(), CREATE_KEYS)
  const sourceType = fields.choice('source_type', ['upload', 'production'] as const)
  const sourceId = fields.text('source_id', { required: true, max: 128, pattern: ID_PATTERN })
  const focus = fields.text('focus', { max: 500 })
  const displayName = fields.text('display_name', { max: DISPLAY_NAME_MAX })
  const modelId = fields.text('model_id', { max: 100, pattern: MODEL_PATTERN })
  const region = fields.text('region', { max: 64, pattern: MODEL_PATTERN })
  fields.assertValid()
  if (!sourceType || !sourceId) throw new HttpError(422, 'source_type and source_id are required')
  const record = store.create({
    source_type: sourceType,
    source_id: sourceId,
    ...resolveSource(sourceType, sourceId),
    display_name: (displayName ?? '').trim(),
    focus: (focus ?? '').trim(),
    model_id: modelId ?? null,
    region: region ?? null,
  })
  return ok({ id: record.id, status: record.status })
}

function timeline(ctx: RouteContext): Reply {
  const record = found(store.get(recordId(ctx)))
  if (record.status !== 'completed') throw new HttpError(409, 'Scene analysis is not completed')
  const body: TimelineResponse = {
    timeline: AD_SPOT_TIMELINE,
    filmstrip: { ...AD_SPOT_FILMSTRIP, url: ctx.mediaUrl(FILMSTRIP_FILE) },
  }
  return ok(body)
}

/** Test helper: `POST /__stub/scene-analysis/{id}/advance` with optional `{"steps": n}` (default 1). */
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
  route('GET', `${BASE}/{id}`, get),
  route('PATCH', `${BASE}/{id}`, patch),
  route('DELETE', `${BASE}/{id}`, remove),
  route('POST', `${BASE}/{id}/archive`, setArchived(true)),
  route('POST', `${BASE}/{id}/unarchive`, setArchived(false)),
  route('POST', `${BASE}/{id}/retry`, retry),
  route('GET', `${BASE}/{id}/timeline`, timeline),
  route('POST', '/__stub/scene-analysis/{id}/advance', advance),
]

export const sceneAnalysisFeature: StubFeature = {
  name: 'scene_analysis',
  routes,
  reset: () => store.reset(),
  usage: (id) => store.get(id)?.usage,
}
