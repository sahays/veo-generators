import { createCrudClient } from './_crud'
import { API_BASE_URL, patchJson, postJson, request } from './_http'

const avatarsCrud = createCrudClient<any>(`${API_BASE_URL}/avatars`, 'avatar')

export const avatars = {
  ...avatarsCrud,
  list: () => avatarsCrud.list(),
  create: (data: {
    name: string
    image_gcs_uri?: string
    style?: string
    persona_prompt?: string
    version?: 'v1' | 'v2'
    voice?: string
    preset_name?: string
    language?: string
    default_greeting?: string
    enable_grounding?: boolean
  }) => postJson<any>(`${API_BASE_URL}/avatars`, data, 'Failed to create avatar'),
  update: (
    id: string,
    data: { name?: string; style?: string; persona_prompt?: string; voice?: string },
  ) => patchJson(`${API_BASE_URL}/avatars/${id}`, data, 'Failed to update avatar'),
  ask: (
    id: string,
    data: {
      question: string
      history?: { role: string; content: string }[]
      model_id?: string
      region?: string
    },
  ) =>
    postJson<{ turn_id: string; answer_text: string; status: string }>(
      `${API_BASE_URL}/avatars/${id}/ask`,
      data,
      'Ask failed',
    ),
  askAudio: (
    id: string,
    audio: Blob,
    history?: { role: string; content: string }[],
  ): Promise<{ turn_id: string; answer_text: string; status: string }> => {
    const fd = new FormData()
    const ext = audio.type.includes('ogg')
      ? 'ogg'
      : audio.type.includes('mp4')
        ? 'm4a'
        : 'webm'
    fd.append('audio', audio, `q.${ext}`)
    if (history?.length) fd.append('history', JSON.stringify(history))
    return request<{ turn_id: string; answer_text: string; status: string }>(
      `${API_BASE_URL}/avatars/${id}/ask-audio`,
      'Ask failed',
      { method: 'POST', body: fd },
    )
  },
  listTurns: (id: string) =>
    request<any[]>(`${API_BASE_URL}/avatars/${id}/turns`, 'Failed to list turns'),
  getTurn: (turnId: string) =>
    request<any>(`${API_BASE_URL}/avatars/turns/${turnId}`, 'Failed to get turn'),
  liveConfig: (id: string) =>
    request<any>(
      `${API_BASE_URL}/avatars/${id}/live-config`,
      'Failed to load live config',
    ),
}
