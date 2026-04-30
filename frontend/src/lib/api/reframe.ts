import { createCrudClient } from './_crud'
import { API_BASE_URL, buildQS, postJson, request } from './_http'

const reframeCrud = createCrudClient<any>(`${API_BASE_URL}/reframe`, 'reframe')

export const reframe = {
  ...reframeCrud,
  list: (params?: { mine?: boolean }) =>
    reframeCrud.list(buildQS({ mine: params?.mine })),
  create: (data: {
    gcs_uri: string
    source_filename?: string
    mime_type?: string
    prompt_id?: string
    content_type?: string
    blurred_bg?: boolean
    sports_mode?: boolean
    vertical_split?: boolean
    model_id?: string
    region?: string
  }) => postJson<any>(`${API_BASE_URL}/reframe`, data, 'Reframe failed'),
  listUploadSources: () =>
    request<any[]>(
      `${API_BASE_URL}/reframe/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<any[]>(
      `${API_BASE_URL}/reframe/sources/productions`,
      'Failed to list production sources',
    ),
}
