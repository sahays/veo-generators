import { API_BASE_URL, postJson } from './_http'

export const chat = {
  sendMessage: (
    message: string,
    history: { role: string; content: string }[] = [],
  ) =>
    postJson<{ response: string; role: string; agent?: string; data?: any }>(
      `${API_BASE_URL}/chat`,
      { message, history },
      'Chat failed',
    ),
}
