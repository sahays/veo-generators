import { createCrudClient } from '../core/_crud'
import {
  API_BASE_URL,
  type JsonValue,
  buildQS,
  postJson,
  request,
} from '../core/_http'

const keyMomentsCrud = createCrudClient<JsonValue>(
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
    postJson<JsonValue>(
      `${API_BASE_URL}/key-moments/analyze`,
      data,
      'Key moments analysis failed',
    ),
  listProductionSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/key-moments/sources/productions`,
      'Failed to list production sources',
    ),
  saveFrames: (id: string, frames: { index: number; gcs_uri: string }[]) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/key-moments/${id}/frames`,
      { frames },
      'Failed to save frames',
    ),
}
