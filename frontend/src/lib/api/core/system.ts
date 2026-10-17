import {
  API_BASE_URL,
  type JsonValue,
  buildQS,
  postJson,
  request,
  requestVoid,
} from './_http'

export const system = {
  getResource: (id: string) =>
    request<JsonValue>(`${API_BASE_URL}/system/resources/${id}`, 'Failed to get resource'),
  listResources: (type?: string, category?: string) => {
    const qs = buildQS({ type, category })
    return request<JsonValue[]>(
      `${API_BASE_URL}/system/resources${qs ? `?${qs}` : ''}`,
      'Failed to list resources',
    )
  },
  createResource: (resource: Record<string, JsonValue>) =>
    postJson<JsonValue>(`${API_BASE_URL}/system/resources`, resource, 'Failed to create resource'),
  activateResource: (id: string) =>
    requestVoid(
      `${API_BASE_URL}/system/resources/${id}/activate`,
      'Failed to activate resource',
      { method: 'POST' },
    ),
  getDefaultSchema: () =>
    request<JsonValue>(`${API_BASE_URL}/system/default-schema`, 'Failed to get default schema'),
}
