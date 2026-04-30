import { useAuthStore } from '@/store/useAuthStore'

export const API_BASE_URL = '/api/v1'

export function getInviteCode(): string {
  return useAuthStore.getState().inviteCode || ''
}

function handleAuthError(res: Response) {
  // 401 = invite code missing/invalid → drop auth and re-gate.
  // 403 = valid user but not master → leave the session alone.
  if (res.status === 401) {
    useAuthStore.getState().logout()
  }
}

export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const code = getInviteCode()
  const headers = new Headers(init?.headers)
  if (code) headers.set('X-Invite-Code', code)
  const res = await fetch(input, { ...init, headers })
  handleAuthError(res)
  if (res.status === 429) {
    const retryAfter = res.headers.get('Retry-After')
    const seconds = retryAfter ? parseInt(retryAfter, 10) : 60
    throw new Error(`Rate limit exceeded. Please wait ${seconds} seconds.`)
  }
  return res
}

async function ensureOk(res: Response, errMsg: string): Promise<Response> {
  if (res.ok) return res
  const body = await res.json().catch(() => ({}))
  throw new Error(body.detail || `${errMsg}: ${res.status}`)
}

export async function request<T>(
  path: string,
  errMsg: string,
  init?: RequestInit,
): Promise<T> {
  const res = await ensureOk(await authFetch(path, init), errMsg)
  return res.json()
}

export async function requestVoid(
  path: string,
  errMsg: string,
  init?: RequestInit,
): Promise<void> {
  await ensureOk(await authFetch(path, init), errMsg)
}

export const jsonInit = (
  method: 'POST' | 'PATCH' | 'PUT',
  body: any,
): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const postJson = <T>(path: string, body: any, err: string) =>
  request<T>(path, err, jsonInit('POST', body))

export const patchJson = (path: string, body: any, err: string) =>
  requestVoid(path, err, jsonInit('PATCH', body))

export const buildQS = (
  params: Record<string, string | boolean | undefined>,
): string => {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === false || v === '') continue
    qs.append(k, v === true ? 'true' : String(v))
  }
  return qs.toString()
}
