import { create } from 'zustand'
import { api } from '@/lib/api'

export interface Message {
  role: 'user' | 'model'
  content: string
  agent?: string
  data?: any
  timestamp: number
  latencyMs?: number
  feedback?: 'up' | 'down'
}

interface ChatState {
  messages: Message[]
  isTyping: boolean
  isOpen: boolean
  isFullscreen: boolean
  setIsOpen: (open: boolean) => void
  setIsFullscreen: (fullscreen: boolean) => void
  setMessageFeedback: (index: number, feedback: 'up' | 'down' | undefined) => void
  sendMessage: (text: string) => Promise<void>
  addSystemMessage: (content: string, data?: any) => void
  clearHistory: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isTyping: false,
  isOpen: false,
  isFullscreen: false,

  setIsOpen: (open) => set({ isOpen: open }),
  setIsFullscreen: (fullscreen) => set({ isFullscreen: fullscreen }),

  setMessageFeedback: (index, feedback) =>
    set((state) => ({
      messages: state.messages.map((m, i) =>
        i === index ? { ...m, feedback } : m,
      ),
    })),

  sendMessage: async (text) => {
    const startedAt = Date.now()
    const userMessage: Message = {
      role: 'user',
      content: text,
      timestamp: startedAt,
    }

    const history = get()
      .messages.slice(-20)
      .map((m) => ({ role: m.role, content: m.content }))

    set((state) => ({
      messages: [...state.messages, userMessage],
      isTyping: true,
    }))

    try {
      const result = await api.chat.sendMessage(text, history)
      const elapsedMs = result.latency_ms ?? Math.max(1, Date.now() - startedAt)

      const modelMessage: Message = {
        role: 'model',
        content: result.response,
        agent: result.agent,
        data: result.data,
        timestamp: Date.now(),
        latencyMs: elapsedMs,
      }

      set((state) => ({
        messages: [...state.messages, modelMessage],
        isTyping: false,
      }))
    } catch (error) {
      console.error('Chat error:', error)
      set({ isTyping: false })

      const errorMessage: Message = {
        role: 'model',
        content:
          'Sorry, I encountered an error processing your request. Please try again later.',
        timestamp: Date.now(),
        latencyMs: Math.max(1, Date.now() - startedAt),
      }
      set((state) => ({ messages: [...state.messages, errorMessage] }))
    }
  },

  addSystemMessage: (content, data) => {
    const msg: Message = {
      role: 'model',
      content,
      agent: 'system',
      data,
      timestamp: Date.now(),
    }
    set((state) => ({ messages: [...state.messages, msg] }))
  },

  clearHistory: () => set({ messages: [] }),
}))

