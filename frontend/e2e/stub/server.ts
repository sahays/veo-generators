/**
 * Local stub of the Veo Generators API for browser tests. No Google Cloud, no FastAPI.
 *
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON e2e/stub/server.ts     (from frontend/)
 *
 * Node >= 22.18 strips the TypeScript types natively; no build step or flag is needed
 * (the flag above only silences a notice about package.json having no "type").
 * Listens on 127.0.0.1:${STUB_PORT:-8787}. Routes live in `routes/`; see README.md.
 */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { HttpError, readJsonObject, sendJson } from './lib/http.ts'
import { log } from './lib/logger.ts'
import { Router, STREAMED, type RouteContext } from './lib/router.ts'
import { MAKE_MEDIA_HINT, missingMedia } from './media.ts'
import { HOST, stubOrigin, stubPort } from './ports.ts'
import { ROUTES } from './routes/index.ts'

const WHO = 'stub.server'
const PORT = stubPort()
const ORIGIN = stubOrigin()
const router = new Router(ROUTES)

interface ParsedUrl {
  path: string
  segments: string[]
  query: URLSearchParams
}

function parseUrl(rawUrl: string): ParsedUrl {
  const queryStart = rawUrl.indexOf('?')
  const path = queryStart === -1 ? rawUrl : rawUrl.slice(0, queryStart)
  const query = new URLSearchParams(queryStart === -1 ? '' : rawUrl.slice(queryStart + 1))
  try {
    const segments = path.split('/').filter((s) => s.length > 0).map((s) => decodeURIComponent(s))
    return { path, segments, query }
  } catch {
    throw new HttpError(400, 'Malformed URL')
  }
}

function preflight(res: ServerResponse): number {
  res.writeHead(204, {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, HEAD, POST, PATCH, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': '*',
    'Access-Control-Max-Age': '600',
  })
  res.end()
  return 204
}

/** Runs the matching handler and returns the status that was sent. */
async function dispatch(req: IncomingMessage, res: ServerResponse, url: ParsedUrl): Promise<number> {
  const method = req.method ?? 'GET'
  if (method === 'OPTIONS') return preflight(res)
  const match = router.match(method === 'HEAD' ? 'GET' : method, url.segments)
  if (match.kind === 'not_found') {
    // Logged as a warning so gaps in the stub are easy to spot while a page renders.
    log('warn', { who: WHO, where: 'dispatch', what: 'unknown_route', why: 'no stub route registered', method, path: url.path })
    throw new HttpError(404, `Stub has no route for ${method} ${url.path}`)
  }
  if (match.kind === 'method_not_allowed') {
    res.setHeader('Allow', match.allow.join(', '))
    throw new HttpError(405, 'Method Not Allowed')
  }
  const ctx: RouteContext = {
    params: match.params,
    query: url.query,
    body: () => readJsonObject(req),
    mediaUrl: (file) => `${ORIGIN}/media/${encodeURIComponent(file)}`,
    req,
    res,
  }
  const result = await match.handler(ctx)
  if (result === STREAMED) return res.statusCode
  sendJson(res, result.status, result.body)
  return result.status
}

function sendFailure(res: ServerResponse, err: unknown): number {
  if (res.headersSent) {
    res.destroy()
    return res.statusCode
  }
  if (err instanceof HttpError) {
    sendJson(res, err.status, { detail: err.detail })
    return err.status
  }
  log('error', { who: WHO, where: 'handle', what: 'handler_crashed', why: err instanceof Error ? err.message : String(err) })
  sendJson(res, 500, { detail: 'Stub server error' })
  return 500
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const started = Date.now()
  const rawUrl = req.url ?? '/'
  let path = rawUrl
  let status: number
  try {
    const url = parseUrl(rawUrl)
    path = url.path
    status = await dispatch(req, res, url)
  } catch (err) {
    status = sendFailure(res, err)
  }
  log('info', { who: WHO, where: 'handle', what: 'request', method: req.method ?? '', path, status, ms: Date.now() - started })
}

async function announce(): Promise<void> {
  log('info', { who: WHO, where: 'main', what: 'listening', how: `${ROUTES.length} routes`, url: ORIGIN })
  const missing = await missingMedia()
  if (missing.length === 0) return
  log('warn', { who: WHO, where: 'main', what: 'media_missing', why: `not generated yet: ${missing.join(', ')}`, how: MAKE_MEDIA_HINT })
}

function main(): void {
  const server = createServer((req, res) => void handle(req, res))
  server.on('error', (err) => {
    log('error', { who: WHO, where: 'main', what: 'server_error', why: err.message })
    process.exit(1)
  })
  const shutdown = (signal: string): void => {
    log('info', { who: WHO, where: 'main', what: 'stopping', why: signal })
    server.close(() => process.exit(0))
    server.closeAllConnections()
  }
  process.on('SIGINT', () => shutdown('SIGINT'))
  process.on('SIGTERM', () => shutdown('SIGTERM'))
  server.listen(PORT, HOST, () => void announce())
}

main()
