import { API_BASE_URL, postJson } from './_http'

export const ai = {
  optimizePrompt: (data: {
    raw_prompt: string
    director_style?: string
    mood?: string
    location?: string
    camera_movement?: string
  }) =>
    postJson<{ refined_prompt: string }>(
      `${API_BASE_URL}/ai/optimize-prompt`,
      data,
      'AI request failed',
    ),
  generateStoryboard: (data: { project_id: string; refined_prompt: string }) =>
    postJson<any[]>(
      `${API_BASE_URL}/ai/generate-storyboard`,
      data,
      'AI request failed',
    ),
  generateVideo: (data: {
    project_id: string
    refined_prompt: string
    video_length: string
  }) =>
    postJson<{ job_id: string; status: string }>(
      `${API_BASE_URL}/ai/generate-video`,
      data,
      'AI request failed',
    ),
}
