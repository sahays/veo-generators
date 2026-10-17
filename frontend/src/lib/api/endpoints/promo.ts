import { createCrudClient } from '../core/_crud'
import { API_BASE_URL, type JsonValue, postJson, request } from '../core/_http'

const promoCrud = createCrudClient<JsonValue>(`${API_BASE_URL}/promo`, 'promo')

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
  }) => postJson<JsonValue>(`${API_BASE_URL}/promo`, data, 'Promo creation failed'),
  listUploadSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/promo/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/promo/sources/productions`,
      'Failed to list production sources',
    ),
}
