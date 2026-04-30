import { createCrudClient } from './_crud'
import { API_BASE_URL, buildQS, postJson, request } from './_http'

const uploadsCrud = createCrudClient<any>(`${API_BASE_URL}/uploads`, 'upload')

export const uploads = {
  ...uploadsCrud,
  list: (params?: { file_type?: string; archived?: boolean }) =>
    uploadsCrud.list(
      buildQS({ file_type: params?.file_type, archived: params?.archived }),
    ),
  compress: (id: string, resolution: string) =>
    postJson<any>(
      `${API_BASE_URL}/uploads/${id}/compress`,
      { resolution },
      'Compression failed',
    ),
  compressStatus: (id: string) =>
    request<any>(
      `${API_BASE_URL}/uploads/${id}/compress-status`,
      'Compress status check failed',
    ),
}
