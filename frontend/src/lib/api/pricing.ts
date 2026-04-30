import { API_BASE_URL, postJson, request } from './_http'

export const pricing = {
  rates: () =>
    request<any>(`${API_BASE_URL}/pricing/rates`, 'Failed to load pricing rates'),
  features: () =>
    request<any>(
      `${API_BASE_URL}/pricing/features`,
      'Failed to load pricing features',
    ),
  estimate: (body: any) =>
    postJson<any>(`${API_BASE_URL}/pricing/estimate`, body, 'Failed to estimate'),
  usage: (feature: string, recordId: string) =>
    request<any>(
      `${API_BASE_URL}/pricing/usage/${feature}/${recordId}`,
      'Failed to load usage',
    ),
}
