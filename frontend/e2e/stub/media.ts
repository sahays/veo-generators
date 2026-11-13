/**
 * `GET /media/{file}`: serves the generated fixture media with HTTP Range
 * support (a browser `<video>` cannot seek without 206 responses).
 *
 * Only plain file names with a known extension are served, and only from
 * `.media/` next to this file; anything else is a 404.
 */
import { createReadStream } from 'node:fs'
import { realpath, stat } from 'node:fs/promises'
import type { ServerResponse } from 'node:http'
import { extname, join, sep } from 'node:path'
import { pipeline } from 'node:stream/promises'
import { HttpError } from './lib/http.ts'
import { log } from './lib/logger.ts'
import { STREAMED, type HandlerResult, type RouteContext } from './lib/router.ts'

export const MEDIA_DIR = join(import.meta.dirname, '.media')
export const VIDEO_FILE = 'ad-spot.mp4'
export const FILMSTRIP_FILE = 'filmstrip.jpg'
export const MAKE_MEDIA_HINT = 'Run: bash e2e/stub/make-media.sh (from frontend/)'

const CONTENT_TYPES: Readonly<Record<string, string>> = {
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.csv': 'text/csv; charset=utf-8',
}

/** No separators and no leading dot, so neither `..` nor dotfiles can be named. */
const SAFE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/
const RANGE_HEADER = /^bytes=(\d{0,15})-(\d{0,15})$/

export type ByteRange =
  | { kind: 'full' }
  | { kind: 'partial'; start: number; end: number }
  | { kind: 'unsatisfiable' }

/**
 * Resolves a `Range` header against a file of `size` bytes.
 * Absent, malformed and multi-range headers are ignored (full response), as RFC 9110 allows.
 */
export function resolveRange(header: string | undefined, size: number): ByteRange {
  const parsed = header ? RANGE_HEADER.exec(header.trim()) : null
  if (!parsed) return { kind: 'full' }
  const [, first, last] = parsed
  if (first === '' && last === '') return { kind: 'full' }
  if (first === '') {
    const suffix = Number(last)
    if (suffix === 0 || size === 0) return { kind: 'unsatisfiable' }
    return { kind: 'partial', start: Math.max(0, size - suffix), end: size - 1 }
  }
  const start = Number(first)
  if (start >= size) return { kind: 'unsatisfiable' }
  const end = last === '' ? size - 1 : Math.min(Number(last), size - 1)
  if (end < start) return { kind: 'full' }
  return { kind: 'partial', start, end }
}

interface MediaFile {
  path: string
  size: number
  contentType: string
  etag: string
  lastModified: string
}

async function locate(name: string): Promise<MediaFile> {
  const contentType = CONTENT_TYPES[extname(name).toLowerCase()]
  if (!SAFE_NAME.test(name) || !contentType) throw new HttpError(404, 'Media file not found')
  try {
    const root = await realpath(MEDIA_DIR)
    const path = await realpath(join(root, name))
    const info = await stat(path)
    // realpath also rejects a symlink that points outside the media directory.
    if (!path.startsWith(root + sep) || !info.isFile()) throw new Error('outside media dir')
    return {
      path,
      size: info.size,
      contentType,
      etag: `"${info.size.toString(16)}-${Math.floor(info.mtimeMs).toString(16)}"`,
      lastModified: info.mtime.toUTCString(),
    }
  } catch {
    throw new HttpError(404, `Media file not found. ${MAKE_MEDIA_HINT}`)
  }
}

function baseHeaders(file: MediaFile): Record<string, string | number> {
  return {
    'Content-Type': file.contentType,
    'Accept-Ranges': 'bytes',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Expose-Headers': 'Accept-Ranges, Content-Length, Content-Range',
    'Cross-Origin-Resource-Policy': 'cross-origin',
    'Cache-Control': 'no-cache',
    ETag: file.etag,
    'Last-Modified': file.lastModified,
  }
}

async function stream(res: ServerResponse, file: MediaFile, start: number, end: number): Promise<void> {
  try {
    await pipeline(createReadStream(file.path, { start, end }), res)
  } catch (err) {
    // A seeking <video> aborts in-flight range requests all the time; that is not an error.
    const code = (err as NodeJS.ErrnoException).code
    if (code === 'ERR_STREAM_PREMATURE_CLOSE' || code === 'ECONNRESET') return
    log('error', { who: 'stub.media', where: 'stream', what: 'stream_failed', why: String(code ?? err) })
    res.destroy()
  }
}

export async function serveMedia(ctx: RouteContext): Promise<HandlerResult> {
  const file = await locate(ctx.params.file)
  const { req, res } = ctx
  const headers = baseHeaders(file)
  // If-Range with a stale validator means "send the whole file again".
  const ifRange = req.headers['if-range']
  const rangeHeader = ifRange && ifRange !== file.etag && ifRange !== file.lastModified ? undefined : req.headers.range
  const range = resolveRange(rangeHeader, file.size)
  if (range.kind === 'unsatisfiable') {
    res.writeHead(416, { ...headers, 'Content-Range': `bytes */${file.size}`, 'Content-Length': 0 })
    res.end()
    return STREAMED
  }
  const start = range.kind === 'partial' ? range.start : 0
  const end = range.kind === 'partial' ? range.end : file.size - 1
  headers['Content-Length'] = end - start + 1
  if (range.kind === 'partial') headers['Content-Range'] = `bytes ${start}-${end}/${file.size}`
  res.writeHead(range.kind === 'partial' ? 206 : 200, headers)
  if (req.method === 'HEAD' || file.size === 0) {
    res.end()
    return STREAMED
  }
  await stream(res, file, start, end)
  return STREAMED
}

/** Names of the expected media files that have not been generated yet. */
export async function missingMedia(): Promise<string[]> {
  const checks = await Promise.all(
    [VIDEO_FILE, FILMSTRIP_FILE].map(async (name) => {
      const found = await stat(join(MEDIA_DIR, name)).then((s) => s.isFile(), () => false)
      return found ? null : name
    }),
  )
  return checks.filter((name): name is string => name !== null)
}
