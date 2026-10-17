import { createCrudClient } from '../core/_crud'
import { API_BASE_URL, type JsonValue, postJson, request } from '../core/_http'

const adaptsCrud = createCrudClient<JsonValue>(`${API_BASE_URL}/adapts`, 'adapt')

export const adapts = {
  ...adaptsCrud,
  list: () => adaptsCrud.list(),
  create: (data: {
    gcs_uri: string
    source_filename?: string
    source_mime_type?: string
    template_gcs_uri?: string
    preset_bundle?: string
    aspect_ratios?: string[]
    model_id?: string
    region?: string
  }) => postJson<JsonValue>(`${API_BASE_URL}/adapts`, data, 'Adapt creation failed'),
  listUploadSources: () =>
    request<JsonValue[]>(
      `${API_BASE_URL}/adapts/sources/uploads`,
      'Failed to list upload sources',
    ),
  listPresets: () =>
    request<JsonValue>(`${API_BASE_URL}/adapts/presets`, 'Failed to list presets'),
}
