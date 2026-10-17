import {
  API_BASE_URL,
  type JsonValue,
  patchJson,
  postJson,
  request,
  requestVoid,
} from './_http'

export const models = {
  list: () => request<JsonValue[]>(`${API_BASE_URL}/models`, 'Failed to list models'),
  defaults: () =>
    request<Record<string, JsonValue>>(
      `${API_BASE_URL}/models/defaults`,
      'Failed to get defaults',
    ),
  regions: () =>
    request<string[]>(`${API_BASE_URL}/models/regions`, 'Failed to list regions'),
  create: (data: {
    name: string
    code: string
    provider: string
    capability: string
    regions?: string[]
    is_default?: boolean
  }) => postJson<JsonValue>(`${API_BASE_URL}/models`, data, 'Failed to create model'),
  setDefault: (id: string) =>
    requestVoid(
      `${API_BASE_URL}/models/${id}/set-default`,
      'Failed to set default',
      { method: 'POST' },
    ),
  update: (id: string, data: Record<string, JsonValue>) =>
    patchJson(`${API_BASE_URL}/models/${id}`, data, 'Failed to update model'),
  delete: (id: string) =>
    requestVoid(`${API_BASE_URL}/models/${id}`, 'Failed to delete model', {
      method: 'DELETE',
    }),
  seed: () =>
    request<JsonValue>(`${API_BASE_URL}/models/seed`, 'Failed to seed models', {
      method: 'POST',
    }),
}
