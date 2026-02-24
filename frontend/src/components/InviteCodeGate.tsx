import { useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, ArrowRight, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'

export const InviteCodeGate = () => {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const login = useAuthStore((s) => s.login)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim()) return

    setIsLoading(true)
    setError('')

    try {
      const result = await api.auth.validate(code.trim())
      if (result.valid) {
        login(code.trim(), result.is_master)
      } else {
        setError('Invalid invite code')
      }
    } catch (err) {
      console.error('Invite code validation error:', err)
      setError(err instanceof Error ? err.message : 'Failed to validate code. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className="w-full max-w-md"
      >
        <div className="glass bg-card rounded-2xl shadow-2xl border border-border p-8">
          <div className="flex flex-col items-center mb-8">
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 20, delay: 0.1 }}
              className="w-14 h-14 rounded-xl bg-accent/20 flex items-center justify-center mb-4"
            >
              <KeyRound size={28} className="text-accent" />
            </motion.div>
            <h1 className="text-2xl font-heading font-bold text-foreground">VeoGen</h1>
            <p className="text-sm text-muted-foreground mt-1">Enter your invite code to continue</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="text"
                value={code}
                onChange={(e) => {
                  setCode(e.target.value)
                  setError('')
                }}
                placeholder="Enter invite code"
                autoFocus
                className="w-full px-4 py-3 rounded-xl bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent transition-all text-sm"
              />
            </div>

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center gap-2 text-sm text-red-500"
              >
                <AlertCircle size={14} />
                <span>{error}</span>
              </motion.div>
            )}

            <motion.button
              type="submit"
              disabled={isLoading || !code.trim()}
              whileHover={!isLoading ? { scale: 1.02 } : {}}
              whileTap={!isLoading ? { scale: 0.98 } : {}}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-accent text-slate-900 font-medium text-sm hover:bg-accent-dark transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <div className="w-4 h-4 border-2 border-slate-900/30 border-t-slate-900 rounded-full animate-spin" />
              ) : (
                <>
                  Continue
                  <ArrowRight size={16} />
                </>
              )}
            </motion.button>
          </form>
        </div>
      </motion.div>
    </div>
  )
}
