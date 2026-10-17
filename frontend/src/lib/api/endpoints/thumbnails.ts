import { createCrudClient } from '../core/_crud'
import {
  API_BASE_URL,
  type JsonValue,
  buildQS,
  postJson,
  request,
} from '../core/_http'

const thumbnailsCrud = createCrudClient<JsonValue>(
  `${API_BASE_URL}/thumbnails`,
  'thumbnail',
)

export const thumbnails = {
  ...thumbnailsCrud,
  list: (params?: { mine?: boolean }) =>
    thumbnailsCrud.list(buildQS({ mine: params?.mine })),
  analyze: (data: {
    gcs_uri: string
    mime_type?: string
    prompt_id: string
    video_filename?: string
    video_source?: string
    production_id?: string
    model_id?: string
    region?: string
  }) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/thumbnails/analyze`,
      data,
      'Thumbnail analysis failed',
    ),
  saveScreenshots: (
    id: string,
    screenshots: { index: number; gcs_uri: string }[],
  ) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/thumbnails/${id}/screenshots`,
      { screenshots },
      'Failed to save screenshots',
    ),
  generateCollage: (id: string, prompt_id: string) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/thumbnails/${id}/collage`,
      { prompt_id },
      'Collage generation failed',
    ),
  listProductionSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/thumbnails/sources/productions`,
      'Failed to list production sources',
    ),
}
