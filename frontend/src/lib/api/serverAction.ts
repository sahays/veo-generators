'use server'

export interface ServerApiResponse {
  status: number
  ok: boolean
  retryAfter: string | null
  text: string
}

const FASTAPI_INTERNAL_ORIGIN =
  process.env.FASTAPI_INTERNAL_ORIGIN || 'http://127.0.0.1:8000'

const AGENTS_SERVICE_ORIGIN =
  process.env.AGENTS_SERVICE_ORIGIN || FASTAPI_INTERNAL_ORIGIN

const PRODUCTIONS_SERVICE_ORIGIN =
  process.env.PRODUCTIONS_SERVICE_ORIGIN || FASTAPI_INTERNAL_ORIGIN

function resolveTargetUrl(path: string): string {
  if (path.startsWith('http')) {
    return path
  }
  const fastapiOrigin =
    process.env.FASTAPI_INTERNAL_ORIGIN || FASTAPI_INTERNAL_ORIGIN
  const agentsOrigin = process.env.AGENTS_SERVICE_ORIGIN || fastapiOrigin
  const productionsOrigin =
    process.env.PRODUCTIONS_SERVICE_ORIGIN || fastapiOrigin

  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const isStoryGraphRoute =
    /^\/api\/v1\/productions\/[^/]+\/(graph|run|stages\/|gates\/|appearances\/|shots\/)/.test(
      normalizedPath,
    )
  const targetOrigin =
    normalizedPath === '/api/v1/chat'
      ? agentsOrigin
      : isStoryGraphRoute
        ? productionsOrigin
        : fastapiOrigin
  return `${targetOrigin}${normalizedPath}`
}

/**
 * Next.js Server Action that executes all API calls server-to-server
 * from the Next.js Node runtime to the FastAPI backend over internal loopback
 * (or to the dedicated Cloud Run services for `/api/v1/chat` and `/api/v1/productions/*`).
 */
export async function serverApiRequest(
  path: string,
  method: string,
  headersRecord: Record<string, string>,
  body?: string | FormData,
): Promise<ServerApiResponse> {
  const url = resolveTargetUrl(path)
  const headers = new Headers(headersRecord)
  if (body instanceof FormData) {
    // Allow Node fetch to generate the multipart/form-data boundary header automatically
    headers.delete('content-type')
  }

  const res = await fetch(url, {
    method,
    headers,
    body: body ?? undefined,
    cache: 'no-store',
  })

  const text = await res.text()
  return {
    status: res.status,
    ok: res.ok,
    retryAfter: res.headers.get('Retry-After'),
    text,
  }
}
