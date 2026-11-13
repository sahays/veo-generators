/** Small HTTP helpers shared by every route module: JSON types, errors, body parsing, responses. */
import type { IncomingMessage, ServerResponse } from 'node:http'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type JsonObject = { [key: string]: JsonValue }

const MAX_BODY_BYTES = 1024 * 1024

/** Thrown by handlers; the server turns it into `{detail}` with the given status (FastAPI style). */
export class HttpError extends Error {
  readonly status: number
  readonly detail: JsonValue

  constructor(status: number, detail: JsonValue) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.name = 'HttpError'
    this.status = status
    this.detail = detail
  }
}

/** FastAPI-shaped 422: `{detail: [{type, loc, msg}]}`, one entry per invalid field. */
export function validationError(issues: Record<string, string>): HttpError {
  const detail: JsonValue = Object.entries(issues).map(([field, msg]) => ({
    type: 'value_error',
    loc: ['body', field],
    msg,
  }))
  return new HttpError(422, detail)
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function readBody(req: IncomingMessage): Promise<Buffer> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    const buf = typeof chunk === 'string' ? Buffer.from(chunk) : (chunk as Buffer)
    size += buf.length
    if (size > MAX_BODY_BYTES) throw new HttpError(413, 'Request body too large')
    chunks.push(buf)
  }
  return Buffer.concat(chunks)
}

/** Parses the request body as a JSON object. An empty body yields `{}`; anything else malformed is a 400. */
export async function readJsonObject(req: IncomingMessage): Promise<JsonObject> {
  const text = (await readBody(req)).toString('utf8').trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new HttpError(400, 'Request body is not valid JSON')
  }
  if (!isJsonObject(parsed)) throw new HttpError(400, 'Request body must be a JSON object')
  return parsed
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = Buffer.from(JSON.stringify(body))
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': payload.length,
    'Cache-Control': 'no-store',
  })
  res.end(payload)
}
