import { API_BASE_URL, type JsonValue, postJson, request } from './_http'

export const diagnostics = {
  optimizePrompt: (data: Record<string, JsonValue>) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/diagnostics/optimize-prompt`,
      data,
      'Diagnostics failed',
    ),
  generateImage: (data: Record<string, JsonValue>) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/diagnostics/generate-image`,
      data,
      'Diagnostics failed',
    ),
  generateVideo: (data: Record<string, JsonValue>) =>
    postJson<JsonValue>(
      `${API_BASE_URL}/diagnostics/generate-video`,
      data,
      'Diagnostics failed',
    ),
  getOperation: (operationName: string) =>
    request<JsonValue>(
      `${API_BASE_URL}/diagnostics/operations/${operationName}`,
      'Operation check failed',
    ),
}
