import { createCrudClient } from '../core/_crud'
import {
  API_BASE_URL,
  type JsonValue,
  buildQS,
  postJson,
  request,
} from '../core/_http'

const uploadsCrud = createCrudClient<JsonValue>(
  `${API_BASE_URL}/uploads`,
  'upload',
)

export const uploads = {
  ...uploadsCrud,
  list: (params?: { file_type?: string; archived?: boolean }) =>
    uploadsCrud.list(
      buildQS({ file_type: params?.file_type, archived: params?.archived }),
    ),
  compress: (id: string, resolution: string) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/uploads/${id}/compress`,
      { resolution },
      'Compression failed',
    ),
  compressStatus: (id: string) =>
    request<JsonValue>(
      `${API_BASE_URL}/uploads/${id}/compress-status`,
      'Compress status check failed',
    ),
}
