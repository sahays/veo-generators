import { createCrudClient } from './_crud'
import { API_BASE_URL, postJson, request } from './_http'

const adaptsCrud = createCrudClient<any>(`${API_BASE_URL}/adapts`, 'adapt')

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
  }) => postJson<any>(`${API_BASE_URL}/adapts`, data, 'Adapt creation failed'),
  listUploadSources: () =>
    request<any[]>(
      `${API_BASE_URL}/adapts/sources/uploads`,
      'Failed to list upload sources',
    ),
  listPresets: () =>
    request<any>(`${API_BASE_URL}/adapts/presets`, 'Failed to list presets'),
}
