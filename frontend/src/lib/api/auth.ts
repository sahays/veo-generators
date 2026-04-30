import {
  API_BASE_URL,
  jsonInit,
  patchJson,
  postJson,
  request,
  requestVoid,
} from './_http'

export const auth = {
  validate: async (
    code: string,
  ): Promise<{ valid: boolean; is_master: boolean }> => {
    // Doesn't go through authFetch — login is open and uses raw fetch.
    const res = await fetch(
      `${API_BASE_URL}/auth/validate`,
      jsonInit('POST', { code }),
    )
    if (res.status === 429) throw new Error('Too many attempts. Please wait a minute.')
    if (!res.ok) throw new Error(`Validation failed: ${res.status}`)
    return res.json()
  },
  listCodes: () =>
    request<any[]>(`${API_BASE_URL}/auth/codes`, 'Failed to list codes'),
  createCode: (data: {
    code: string
    label?: string
    daily_credits?: number
    expires_at?: string
  }) => postJson<any>(`${API_BASE_URL}/auth/codes`, data, 'Failed to create code'),
  revokeCode: (id: string) =>
    requestVoid(
      `${API_BASE_URL}/auth/codes/${id}/revoke`,
      'Failed to revoke code',
      { method: 'POST' },
    ),
  activateCode: (id: string) =>
    requestVoid(
      `${API_BASE_URL}/auth/codes/${id}/activate`,
      'Failed to activate code',
      { method: 'POST' },
    ),
  deleteCode: (id: string) =>
    requestVoid(
      `${API_BASE_URL}/auth/codes/${id}`,
      'Failed to delete code',
      { method: 'DELETE' },
    ),
  updateCode: (
    id: string,
    data: { daily_credits?: number; expires_at?: string | null },
  ) =>
    patchJson(`${API_BASE_URL}/auth/codes/${id}`, data, 'Failed to update code'),
}
