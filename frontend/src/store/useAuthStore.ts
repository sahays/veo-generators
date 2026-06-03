import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  inviteCode: string | null
  isMaster: boolean
  // Power users have full access to every feature except invite-code
  // management. Master is a superset (isMaster implies power privileges).
  isPower: boolean
  isAuthenticated: boolean
  login: (code: string, isMaster: boolean, isPower?: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      inviteCode: null,
      isMaster: false,
      isPower: false,
      isAuthenticated: false,
      login: (code, isMaster, isPower = false) =>
        set({
          inviteCode: code,
          isMaster,
          isPower,
          isAuthenticated: true,
        }),
      logout: () =>
        set({
          inviteCode: null,
          isMaster: false,
          isPower: false,
          isAuthenticated: false,
        }),
    }),
    { name: 'veo-auth' }
  )
)
