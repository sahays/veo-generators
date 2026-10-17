import { createCrudClient } from '../core/_crud'
import {
  API_BASE_URL,
  type JsonValue,
  buildQS,
  postJson,
  request,
} from '../core/_http'

const reframeCrud = createCrudClient<JsonValue>(
  `${API_BASE_URL}/reframe`,
  'reframe',
)

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
    diagnostic_mode?: boolean
    output_aspect_ratio?: '9:16' | '3:4'
    model_id?: string
    region?: string
  }) => postJson<JsonValue>(`${API_BASE_URL}/reframe`, data, 'Reframe failed'),
  listUploadSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/reframe/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/reframe/sources/productions`,
      'Failed to list production sources',
    ),
}
