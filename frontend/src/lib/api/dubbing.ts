import { createCrudClient } from './_crud'
import { API_BASE_URL, postJson, request } from './_http'

const dubbingCrud = createCrudClient<any>(`${API_BASE_URL}/dubbing`, 'dub')

export interface DubLanguage {
  code: string
  name: string
  // Group label for the picker ("English" | "European" | "Indian"). Presentation
  // only — the backend allowlist is what actually validates a code.
  region: string
}

export interface DubLanguagesResponse {
  languages: DubLanguage[]
  max_languages: number
  max_source_minutes: number
}

export const dubbing = {
  ...dubbingCrud,
  create: (data: {
    gcs_uri: string
    source_filename?: string
    language_codes: string[]
    duration_sec?: number
    model_id?: string
  }) => postJson<any>(`${API_BASE_URL}/dubbing`, data, 'Dubbing failed'),
  // Served by the backend so the picker can't drift from the allowlist the
  // router validates against.
  listLanguages: () =>
    request<DubLanguagesResponse>(
      `${API_BASE_URL}/dubbing/languages`,
      'Failed to list dubbing languages',
    ),
  listUploadSources: () =>
    request<any[]>(
      `${API_BASE_URL}/dubbing/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<any[]>(
      `${API_BASE_URL}/dubbing/sources/productions`,
      'Failed to list production sources',
    ),
}
