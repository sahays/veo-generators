import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface CreditCosts {
  video: number
  image: number
  text: number
}

interface AuthState {
  inviteCode: string | null
  isMaster: boolean
  isAuthenticated: boolean
  dailyCredits: number | null
  dailyUsage: number
  creditCosts: CreditCosts
  login: (code: string, isMaster: boolean, dailyCredits?: number | null, dailyUsage?: number, creditCosts?: CreditCosts) => void
  logout: () => void
  refreshCredits: () => Promise<void>
}

const DEFAULT_CREDIT_COSTS: CreditCosts = { video: 5, image: 2, text: 1 }

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      inviteCode: null,
      isMaster: false,
      isAuthenticated: false,
      dailyCredits: null,
      dailyUsage: 0,
      creditCosts: DEFAULT_CREDIT_COSTS,
      login: (code, isMaster, dailyCredits, dailyUsage, creditCosts) =>
        set({
          inviteCode: code,
          isMaster,
          isAuthenticated: true,
          dailyCredits: dailyCredits ?? null,
          dailyUsage: dailyUsage ?? 0,
          creditCosts: creditCosts ?? DEFAULT_CREDIT_COSTS,
        }),
      logout: () =>
        set({
          inviteCode: null,
          isMaster: false,
          isAuthenticated: false,
          dailyCredits: null,
          dailyUsage: 0,
          creditCosts: DEFAULT_CREDIT_COSTS,
        }),
      refreshCredits: async () => {
        const { inviteCode } = get()
        if (!inviteCode) return
        try {
          const res = await fetch('/api/v1/auth/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code: inviteCode }),
          })
          if (!res.ok) return
          const data = await res.json()
          if (data.valid) {
            set({
              dailyCredits: data.daily_credits ?? null,
              dailyUsage: data.daily_usage ?? 0,
              creditCosts: data.credit_costs ?? DEFAULT_CREDIT_COSTS,
            })
          }
        } catch {
          // silently fail
        }
      },
    }),
    { name: 'veo-auth' }
  )
)
