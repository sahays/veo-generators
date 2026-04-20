import { create } from 'zustand'
import { api } from '@/lib/api'

export interface Message {
  role: 'user' | 'model'
  content: string
  agent?: string
  data?: any
  timestamp: number
}

interface ChatState {
  messages: Message[]
  isTyping: boolean
  isOpen: boolean
  setIsOpen: (open: boolean) => void
  sendMessage: (text: string) => Promise<void>
  addSystemMessage: (content: string, data?: any) => void
  clearHistory: () => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isTyping: false,
  isOpen: false,

  setIsOpen: (open) => set({ isOpen: open }),

  sendMessage: async (text) => {
    const userMessage: Message = {
      role: 'user',
      content: text,
      timestamp: Date.now()
    }

    const history = get().messages.slice(-20).map(m => ({ role: m.role, content: m.content }))

    set((state) => ({
      messages: [...state.messages, userMessage],
      isTyping: true
    }))

    try {
      const result = await api.chat.sendMessage(text, history)
      
      const modelMessage: Message = {
        role: 'model',
        content: result.response,
        agent: result.agent,
        data: result.data,
        timestamp: Date.now()
      }

      set((state) => ({ 
        messages: [...state.messages, modelMessage],
        isTyping: false 
      }))
    } catch (error) {
      console.error('Chat error:', error)
      set({ isTyping: false })
      
      const errorMessage: Message = {
        role: 'model',
        content: "Sorry, I encountered an error processing your request. Please try again later.",
        timestamp: Date.now()
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

  clearHistory: () => set({ messages: [] })
}))
