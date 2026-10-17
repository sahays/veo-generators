import { API_BASE_URL, postJson, serverFetch } from './_http'

export interface SharedChatMessageItem {
  role: 'user' | 'model'
  content: string
  agent?: string
  latency_ms?: number
  timestamp?: number
}

export interface SharedChatRecord {
  id: string
  title: string
  created_at: string
  messages: SharedChatMessageItem[]
}

export const chat = {
  sendMessage: (
    message: string,
    history: { role: string; content: string }[] = [],
  ) =>
    postJson<{
      response: string
      role: string
      agent?: string
      latency_ms?: number
      data?: any
    }>(`${API_BASE_URL}/chat`, { message, history }, 'Chat failed'),

  shareChat: (payload: {
    title?: string
    messages: SharedChatMessageItem[]
  }) =>
    postJson<{ id: string; title: string; created_at: string }>(
      `${API_BASE_URL}/chat/share`,
      payload,
      'Failed to share chat',
    ),

  getSharedChat: async (shareId: string): Promise<SharedChatRecord> => {
    const res = await serverFetch(`${API_BASE_URL}/chat/share/${shareId}`)
    if (!res.ok) {
      throw new Error('Shared chat not found')
    }
    return res.json()
  },
}

