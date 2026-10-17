import { API_BASE_URL, type JsonValue, postJson, request } from './_http'

export const pricing = {
  rates: () =>
    request<JsonValue>(`${API_BASE_URL}/pricing/rates`, 'Failed to load pricing rates'),
  features: () =>
    request<JsonValue>(
      `${API_BASE_URL}/pricing/features`,
      'Failed to load pricing features',
    ),
  estimate: (body: Record<string, JsonValue>) =>
    postJson<JsonValue>(`${API_BASE_URL}/pricing/estimate`, body, 'Failed to estimate'),
  usage: (feature: string, recordId: string) =>
    request<JsonValue>(
      `${API_BASE_URL}/pricing/usage/${feature}/${recordId}`,
      'Failed to load usage',
    ),
}
