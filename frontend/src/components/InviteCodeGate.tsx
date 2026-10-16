import { useState } from 'react'
import { motion } from 'framer-motion'
import { KeyRound, ArrowRight, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { useToastStore } from '@/store/useToastStore'
import { inviteCodeFormSchema } from '@/types/schemas'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export const InviteCodeGate = () => {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const login = useAuthStore((s) => s.login)
  const addToast = useToastStore((s) => s.addToast)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const parsed = inviteCodeFormSchema.safeParse({ code })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message || 'Invalid invite code')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const result = await api.auth.validate(parsed.data.code)
      if (result.valid) {
        login(parsed.data.code, result.is_master, result.is_power)
        addToast({
          title: 'Welcome to VeoGen',
          description: result.is_master
            ? 'Signed in with master privileges'
            : result.is_power
              ? 'Signed in with power privileges'
              : 'Signed in as guest viewer',
          variant: 'success',
        })
      } else {
        setError('Invalid invite code')
      }
    } catch (err) {
      console.error('Invite code validation error:', err)
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to validate code. Please try again.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background bg-accent-gradient p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 320, damping: 28 }}
        className="w-full max-w-md"
      >
        <div className="glass card-interactive bg-card rounded-xl shadow-2xl border border-border overflow-hidden">
          <div className="h-1 w-full bg-gradient-to-r from-orange-700 via-orange-500 to-amber-400" />
          <div className="p-8">
            <div className="flex flex-col items-center mb-8">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{
                  type: 'spring',
                  stiffness: 400,
                  damping: 20,
                  delay: 0.08,
                }}
                className="w-14 h-14 rounded-xl bg-gradient-to-br from-orange-600/20 to-amber-500/15 border border-accent/25 flex items-center justify-center mb-4 shadow-glow-sm"
              >
                <KeyRound size={26} className="text-accent" />
              </motion.div>
              <h1 className="text-2xl font-heading font-bold text-foreground">
                VeoGen
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Enter your master invite code to continue
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <Input
                type="text"
                value={code}
                onChange={(e) => {
                  setCode(e.target.value)
                  setError('')
                }}
                placeholder="Enter master invite code"
                autoFocus
                className="py-3 bg-muted/60"
              />

              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex items-center gap-2 text-xs text-red-500 bg-red-500/10 border border-red-500/20 rounded-[5px] px-3 py-2"
                >
                  <AlertCircle size={14} className="shrink-0" />
                  <span>{error}</span>
                </motion.div>
              )}

              <Button
                type="submit"
                size="lg"
                disabled={isLoading || !code.trim()}
                className="w-full justify-center py-3"
              >
                {isLoading ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>
                    Continue
                    <ArrowRight size={16} />
                  </>
                )}
              </Button>
            </form>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
