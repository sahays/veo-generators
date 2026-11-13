/**
 * The direct-upload flow behind `api.assets.directUpload` (`src/lib/api/endpoints/assets.ts`),
 * as `api/routers/media/uploads.py` implements it against GCS:
 *
 *   1. `POST /api/v1/assets/upload/init`      → `{record_id, upload_url, ...}`; the record is `pending`
 *   2. `PUT  {upload_url}` (from the browser) → the file bytes; here `/__stub/upload/{record_id}`
 *   3. `POST /api/v1/assets/upload/complete`  → `{id, gcs_uri, signed_url, file_type}`; the record is `completed`
 *
 * The bytes are counted and thrown away. Uploaded records get the ids
 * `upl-stub-1`, `upl-stub-2`, ... and are dropped by `POST /__stub/reset`.
 */
import type { IncomingMessage } from 'node:http'
import type { UploadRecord } from '../../../src/types/records.ts'
import { findUpload } from '../data/catalog.ts'
import type { StubFeature } from '../lib/feature.ts'
import { HttpError, validationError, type JsonObject } from '../lib/http.ts'
import { log } from '../lib/logger.ts'
import { STREAMED, ok, route, type HandlerResult, type Reply, type Route, type RouteContext } from '../lib/router.ts'
import { VIDEO_FILE } from '../media.ts'
import { stubOrigin } from '../ports.ts'

const WHO = 'stub.uploads'
const API = '/api/v1'
const UPLOAD_PATH = '/__stub/upload'
const MAX_UPLOAD_BYTES = 12 * 1024 * 1024
const MAX_FILENAME_CHARS = 300
const UPLOAD_URL_TTL_MS = 15 * 60 * 1000
const TOO_LARGE = `The stub accepts uploads of up to ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`

interface Entry {
  record: UploadRecord
  /** Size of the body the browser PUT, or null while no bytes have arrived. */
  receivedBytes: number | null
}

const entries = new Map<string, Entry>()
let created = 0

function resetUploads(): void {
  entries.clear()
  created = 0
}

/** An upload by id: a catalog fixture, or a record created through the upload flow (any status). */
export function lookupUpload(id: string): UploadRecord | undefined {
  const uploaded = entries.get(id)?.record
  return findUpload(id) ?? (uploaded ? { ...uploaded } : undefined)
}

/** Records whose upload finished, newest first. */
export function completedUploads(): UploadRecord[] {
  const done = [...entries.values()].filter((entry) => entry.record.status === 'completed')
  return done.reverse().map((entry) => ({ ...entry.record }))
}

/** As the real router: the MIME type decides between `video`, `image` and `other`. */
function fileTypeFor(mime: string): UploadRecord['file_type'] {
  if (mime.startsWith('video/')) return 'video'
  return mime.startsWith('image/') ? 'image' : 'other'
}

function requiredText(body: JsonObject, key: string, max: number): string {
  const value = body[key]
  if (value === undefined || value === null) throw validationError({ [key]: 'Field required' })
  if (typeof value !== 'string') throw validationError({ [key]: 'Input should be a valid string' })
  if (value.length > max) throw validationError({ [key]: `String should have at most ${max} characters` })
  return value
}

function declaredSize(body: JsonObject): number {
  const value = body.file_size_bytes ?? 0
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw validationError({ file_size_bytes: 'Input should be a valid integer' })
  }
  return value
}

function newRecord(id: string, filename: string, contentType: string, sizeBytes: number): UploadRecord {
  return {
    id,
    filename,
    mime_type: contentType,
    file_type: fileTypeFor(contentType),
    gcs_uri: `gs://fixture-bucket/uploads/${id}-${filename}`,
    file_size_bytes: sizeBytes,
    status: 'pending',
    compressed_variants: [],
    archived: false,
    createdAt: new Date().toISOString(),
  }
}

async function init(ctx: RouteContext): Promise<Reply> {
  const body = await ctx.body()
  const filename = requiredText(body, 'filename', MAX_FILENAME_CHARS)
  const contentType = requiredText(body, 'content_type', MAX_FILENAME_CHARS)
  const record = newRecord(`upl-stub-${++created}`, filename, contentType, declaredSize(body))
  entries.set(record.id, { record, receivedBytes: null })
  return ok({
    record_id: record.id,
    upload_url: `${stubOrigin()}${UPLOAD_PATH}/${record.id}`,
    gcs_uri: record.gcs_uri,
    content_type: contentType,
    expires_at: new Date(Date.now() + UPLOAD_URL_TTL_MS).toISOString(),
  })
}

/** Reads the body to its end without keeping it; returns its size. */
async function drain(req: IncomingMessage): Promise<number> {
  let size = 0
  for await (const chunk of req) {
    size += typeof chunk === 'string' ? Buffer.byteLength(chunk) : (chunk as Buffer).length
    if (size > MAX_UPLOAD_BYTES) throw new HttpError(413, TOO_LARGE)
  }
  return size
}

/** The browser's `PUT {upload_url}`: stands in for the signed GCS URL, so it answers with CORS headers. */
async function receive(ctx: RouteContext): Promise<HandlerResult> {
  const { req, res } = ctx
  // Set before anything can throw: an error reply without it reads as a network failure in the browser.
  res.setHeader('Access-Control-Allow-Origin', '*')
  const entry = entries.get(ctx.params.record_id)
  if (!entry) throw new HttpError(404, 'Upload not found')
  if (Number(req.headers['content-length'] ?? 0) > MAX_UPLOAD_BYTES) throw new HttpError(413, TOO_LARGE)
  entry.receivedBytes = await drain(req)
  log('info', { who: WHO, where: 'receive', what: 'upload_received', how: 'bytes counted, not stored', id: entry.record.id, bytes: entry.receivedBytes })
  res.writeHead(200, { 'Content-Length': 0 })
  res.end()
  return STREAMED
}

async function complete(ctx: RouteContext): Promise<Reply> {
  const recordId = requiredText(await ctx.body(), 'record_id', MAX_FILENAME_CHARS)
  const entry = entries.get(recordId)
  if (!entry) throw new HttpError(404, 'Upload not found')
  const { record } = entry
  if (entry.receivedBytes === null) {
    record.status = 'failed'
    throw new HttpError(400, 'File not found in GCS')
  }
  record.status = 'completed'
  record.file_size_bytes = entry.receivedBytes
  return ok({
    id: record.id,
    gcs_uri: record.gcs_uri,
    // Only videos have something to play: the fixture video. Other files have no readable copy here.
    signed_url: record.file_type === 'video' ? ctx.mediaUrl(VIDEO_FILE) : '',
    file_type: record.file_type,
  })
}

const routes: Route[] = [
  route('POST', `${API}/assets/upload/init`, init),
  route('PUT', `${UPLOAD_PATH}/{record_id}`, receive),
  route('POST', `${API}/assets/upload/complete`, complete),
]

/** Not a priced feature (no `usage`); listed in `routes/index.ts` for its routes and its reset hook. */
export const uploadsFeature: StubFeature = {
  name: 'uploads',
  routes,
  reset: resetUploads,
}
