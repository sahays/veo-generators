'use server'

export interface ServerApiResponse {
  status: number
  ok: boolean
  retryAfter: string | null
  text: string
}

const FASTAPI_INTERNAL_ORIGIN =
  process.env.FASTAPI_INTERNAL_ORIGIN || 'http://127.0.0.1:8000'

/**
 * Next.js Server Action that executes all API calls server-to-server
 * from the Next.js Node runtime to the FastAPI backend over internal loopback.
 */
export async function serverApiRequest(
  path: string,
  method: string,
  headersRecord: Record<string, string>,
  body?: string | FormData,
): Promise<ServerApiResponse> {
  const url = path.startsWith('http')
    ? path
    : `${FASTAPI_INTERNAL_ORIGIN}${path.startsWith('/') ? path : `/${path}`}`

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
