import { createCrudClient } from './_crud'
import { API_BASE_URL, buildQS, postJson, request } from './_http'

const keyMomentsCrud = createCrudClient<any>(
  `${API_BASE_URL}/key-moments`,
  'key moments',
)

export const keyMoments = {
  ...keyMomentsCrud,
  list: (params?: { mine?: boolean }) =>
    keyMomentsCrud.list(buildQS({ mine: params?.mine })),
  analyze: (data: {
    gcs_uri: string
    mime_type?: string
    prompt_id: string
    schema_id?: string
    video_filename?: string
    video_source?: string
    production_id?: string
    model_id?: string
    region?: string
  }) =>
    postJson<any>(
      `${API_BASE_URL}/key-moments/analyze`,
      data,
      'Key moments analysis failed',
    ),
  listProductionSources: () =>
    request<any[]>(
      `${API_BASE_URL}/key-moments/sources/productions`,
      'Failed to list production sources',
    ),
}
