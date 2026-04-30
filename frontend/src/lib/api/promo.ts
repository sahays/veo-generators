import { createCrudClient } from './_crud'
import { API_BASE_URL, postJson, request } from './_http'

const promoCrud = createCrudClient<any>(`${API_BASE_URL}/promo`, 'promo')

export const promo = {
  ...promoCrud,
  list: () => promoCrud.list(),
  create: (data: {
    gcs_uri: string
    source_filename?: string
    prompt_id?: string
    target_duration?: number
    text_overlay?: boolean
    generate_thumbnail?: boolean
    model_id?: string
    region?: string
  }) => postJson<any>(`${API_BASE_URL}/promo`, data, 'Promo creation failed'),
  listUploadSources: () =>
    request<any[]>(
      `${API_BASE_URL}/promo/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<any[]>(
      `${API_BASE_URL}/promo/sources/productions`,
      'Failed to list production sources',
    ),
}
