import { API_BASE_URL, postJson } from './_http'

export const diagnostics = {
  optimizePrompt: (data: any) =>
    postJson<any>(`${API_BASE_URL}/diagnostics/optimize-prompt`, data, 'Diagnostics failed'),
  generateImage: (data: any) =>
    postJson<any>(`${API_BASE_URL}/diagnostics/generate-image`, data, 'Diagnostics failed'),
  generateVideo: (data: any) =>
    postJson<any>(`${API_BASE_URL}/diagnostics/generate-video`, data, 'Diagnostics failed'),
}
