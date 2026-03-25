import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  inviteCode: string | null
  isMaster: boolean
  isAuthenticated: boolean
  login: (code: string, isMaster: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      inviteCode: null,
      isMaster: false,
      isAuthenticated: false,
      login: (code, isMaster) =>
        set({
          inviteCode: code,
          isMaster,
          isAuthenticated: true,
        }),
      logout: () =>
        set({
          inviteCode: null,
          isMaster: false,
          isAuthenticated: false,
        }),
    }),
    { name: 'veo-auth' }
  )
)
