import { authFetch } from './_http'

/** Error carrying the human-readable issues from a 422 response `detail`. */
export class ApiValidationError extends Error {
  readonly issues: string[]

  constructor(message: string, issues: string[]) {
    super(message)
    this.name = 'ApiValidationError'
    this.issues = issues
  }
}

type DetailItem = string | { message?: unknown; msg?: unknown; code?: unknown }

function describeItem(item: DetailItem): string {
  if (typeof item === 'string') return item
  const text = item.message ?? item.msg ?? item.code
  return typeof text === 'string' ? text : JSON.stringify(item)
}

/**
 * Normalise a FastAPI `detail` payload (string, list of strings/issues, or
 * `{issues: [...]}`) into a flat list of messages.
 */
export function extractDetailIssues(detail: unknown): string[] {
  if (typeof detail === 'string') return [detail]
  if (Array.isArray(detail)) return detail.map((d) => describeItem(d as DetailItem))
  if (detail && typeof detail === 'object') {
    const nested = (detail as { issues?: unknown; message?: unknown }).issues
    if (Array.isArray(nested)) return extractDetailIssues(nested)
    return [describeItem(detail as DetailItem)]
  }
  return []
}

/**
 * JSON request that surfaces 422 responses as {@link ApiValidationError}
 * (with every issue preserved) and other failures as plain `Error`s.
 */
export async function requestWithValidation<T>(path: string, errMsg: string, init: RequestInit): Promise<T> {
  const res = await authFetch(path, init)
  if (res.ok) return (await res.json()) as T
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
  const issues = extractDetailIssues(body.detail)
  if (res.status === 422) throw new ApiValidationError(errMsg, issues)
  throw new Error(issues.join('; ') || `${errMsg}: ${res.status}`)
}
