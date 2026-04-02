import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Shield, Trash2, Ban, CheckCircle, Shuffle, Pencil, Check, X, CalendarClock } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/Common'
import { Modal } from '@/components/Modal'
import { cn } from '@/lib/utils'

interface InviteCode {
  id: string
  code: string
  label: string
  is_active: boolean
  daily_credits: number
  expires_at: string | null
  createdAt: string
}

const EXPIRY_OPTIONS = [
  { value: '', label: 'No expiry' },
  { value: '1w', label: '1 week' },
  { value: '2w', label: '2 weeks' },
  { value: '1m', label: '1 month' },
  { value: '3m', label: '3 months' },
  { value: '6m', label: '6 months' },
]

function computeExpiryDate(duration: string, from: Date = new Date()): string | null {
  if (!duration) return null
  const d = new Date(from)
  switch (duration) {
    case '1w': d.setDate(d.getDate() + 7); break
    case '2w': d.setDate(d.getDate() + 14); break
    case '1m': d.setMonth(d.getMonth() + 1); break
    case '3m': d.setMonth(d.getMonth() + 3); break
    case '6m': d.setMonth(d.getMonth() + 6); break
    default: return null
  }
  return d.toISOString()
}

export const InviteCodesPage = () => {
  const [codes, setCodes] = useState<InviteCode[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newDailyCredits, setNewDailyCredits] = useState('250')
  const [newExpiryDuration, setNewExpiryDuration] = useState('')
  const [createError, setCreateError] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [editingLimitId, setEditingLimitId] = useState<string | null>(null)
  const [editingLimitValue, setEditingLimitValue] = useState('')
  const [extendingId, setExtendingId] = useState<string | null>(null)
  const [extendDuration, setExtendDuration] = useState('1m')
  const [isExtending, setIsExtending] = useState(false)

  const generateRandomCode = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    let result = ''
    const array = new Uint8Array(16)
    crypto.getRandomValues(array)
    for (let i = 0; i < 16; i++) result += chars[array[i] % chars.length]
    setNewCode(result)
    setCreateError('')
  }

  const fetchCodes = () => {
    api.auth.listCodes()
      .then(setCodes)
      .catch((err) => console.error('Failed to fetch codes', err))
      .finally(() => setIsLoading(false))
  }

  useEffect(() => { fetchCodes() }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newCode.trim()) return

    setIsCreating(true)
    setCreateError('')
    try {
      const data: { code: string; label?: string; daily_credits?: number; expires_at?: string } = { code: newCode.trim() }
      if (newLabel.trim()) data.label = newLabel.trim()
      const credits = parseInt(newDailyCredits, 10)
      if (!isNaN(credits) && credits > 0) data.daily_credits = credits
      const expiryDate = computeExpiryDate(newExpiryDuration)
      if (expiryDate) data.expires_at = expiryDate
      await api.auth.createCode(data)
      setShowCreateModal(false)
      setNewCode('')
      setNewLabel('')
      setNewDailyCredits('250')
      setNewExpiryDuration('')
      fetchCodes()
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create code')
    } finally {
      setIsCreating(false)
    }
  }

  const handleExtend = async (id: string) => {
    setIsExtending(true)
    try {
      const code = codes.find(c => c.id === id)
      // Extend from current expiry if still in the future, otherwise from now
      const base = code?.expires_at && new Date(code.expires_at) > new Date()
        ? new Date(code.expires_at)
        : new Date()
      const newExpiry = computeExpiryDate(extendDuration, base)
      await api.auth.updateCode(id, { expires_at: newExpiry })
      setExtendingId(null)
      fetchCodes()
    } catch (err) {
      console.error('Failed to extend expiry', err)
    } finally {
      setIsExtending(false)
    }
  }

  const handleRevoke = async (id: string) => {
    await api.auth.revokeCode(id)
    fetchCodes()
  }

  const handleActivate = async (id: string) => {
    await api.auth.activateCode(id)
    fetchCodes()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Permanently delete this invite code?')) return
    await api.auth.deleteCode(id)
    fetchCodes()
  }

  const handleSaveDailyCredits = async (id: string) => {
    const val = parseInt(editingLimitValue, 10)
    if (isNaN(val) || val < 1) return
    try {
      await api.auth.updateCode(id, { daily_credits: val })
      setEditingLimitId(null)
      fetchCodes()
    } catch (err) {
      console.error('Failed to update daily credits', err)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield size={24} className="text-accent" />
          <h1 className="text-2xl font-heading font-bold text-foreground">Invite Codes</h1>
        </div>
        <Button icon={Plus} onClick={() => setShowCreateModal(true)}>
          New Code
        </Button>
      </div>

      {codes.length === 0 ? (
        <div className="glass bg-card rounded-xl p-12 text-center">
          <p className="text-muted-foreground">No invite codes yet. Create one to get started.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {codes.map((code) => {
            const isExpired = code.expires_at && new Date(code.expires_at) < new Date()
            const isActive = code.is_active && !isExpired
            const isEditingLimit = editingLimitId === code.id
            const isExtendingThis = extendingId === code.id

            return (
              <motion.div
                key={code.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="glass bg-card rounded-xl border border-border p-4 flex items-center justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <code className="text-sm font-mono font-bold text-foreground">{code.code}</code>
                    <span className={cn(
                      "text-xs px-2 py-0.5 rounded-full font-medium",
                      isActive
                        ? "bg-green-500/15 text-green-600 dark:text-green-400"
                        : "bg-red-500/15 text-red-600 dark:text-red-400"
                    )}>
                      {isExpired ? 'Expired' : isActive ? 'Active' : 'Revoked'}
                    </span>
                    {isEditingLimit ? (
                      <span className="inline-flex items-center gap-1">
                        <input
                          type="number"
                          min="1"
                          value={editingLimitValue}
                          onChange={(e) => setEditingLimitValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveDailyCredits(code.id)
                            if (e.key === 'Escape') setEditingLimitId(null)
                          }}
                          autoFocus
                          className="w-20 px-1.5 py-0.5 rounded bg-muted border border-border text-foreground text-xs text-center focus:outline-none focus:ring-1 focus:ring-accent/50"
                        />
                        <button onClick={() => handleSaveDailyCredits(code.id)} className="text-green-500 hover:text-green-600">
                          <Check size={14} />
                        </button>
                        <button onClick={() => setEditingLimitId(null)} className="text-muted-foreground hover:text-foreground">
                          <X size={14} />
                        </button>
                      </span>
                    ) : (
                      <button
                        onClick={() => { setEditingLimitId(code.id); setEditingLimitValue(String(code.daily_credits ?? 250)) }}
                        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-blue-500/15 text-blue-600 dark:text-blue-400 hover:bg-blue-500/25 transition-colors"
                      >
                        {code.daily_credits ?? 250} credits/day
                        <Pencil size={10} />
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
                    {code.label && <span>{code.label}</span>}
                    {code.expires_at ? (
                      <span className={cn(isExpired && 'text-red-500')}>
                        {isExpired ? 'Expired' : 'Expires'}: {new Date(code.expires_at).toLocaleDateString()}
                      </span>
                    ) : (
                      <span>No expiry</span>
                    )}
                    <span>Created: {new Date(code.createdAt).toLocaleDateString()}</span>
                  </div>

                  {/* Inline extend UI */}
                  {isExtendingThis && (
                    <div className="flex items-center gap-2 mt-2">
                      <select
                        value={extendDuration}
                        onChange={(e) => setExtendDuration(e.target.value)}
                        className="px-2 py-1 rounded-lg bg-muted border border-border text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-accent/50"
                      >
                        {EXPIRY_OPTIONS.filter(o => o.value).map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                      <span className="text-[10px] text-muted-foreground">
                        from {code.expires_at && new Date(code.expires_at) > new Date()
                          ? new Date(code.expires_at).toLocaleDateString()
                          : 'now'}
                      </span>
                      <button
                        onClick={() => handleExtend(code.id)}
                        disabled={isExtending}
                        className="text-xs px-2 py-1 rounded-lg bg-accent/10 text-accent-dark hover:bg-accent/20 transition-colors font-medium disabled:opacity-50"
                      >
                        {isExtending ? 'Saving...' : 'Apply'}
                      </button>
                      <button
                        onClick={() => setExtendingId(null)}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    icon={CalendarClock}
                    onClick={() => { setExtendingId(extendingId === code.id ? null : code.id); setExtendDuration('1m') }}
                    className="text-xs px-2 py-1"
                  >
                    Extend
                  </Button>
                  {code.is_active ? (
                    <Button
                      variant="ghost"
                      icon={Ban}
                      onClick={() => handleRevoke(code.id)}
                      className="text-xs px-2 py-1"
                    >
                      Revoke
                    </Button>
                  ) : (
                    <Button
                      variant="ghost"
                      icon={CheckCircle}
                      onClick={() => handleActivate(code.id)}
                      className="text-xs px-2 py-1"
                    >
                      Activate
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    icon={Trash2}
                    onClick={() => handleDelete(code.id)}
                    className="text-xs px-2 py-1 text-red-500 hover:text-red-600"
                  >
                    Delete
                  </Button>
                </div>
              </motion.div>
            )
          })}
        </div>
      )}

      <Modal
        isOpen={showCreateModal}
        onClose={() => { setShowCreateModal(false); setCreateError('') }}
        title="Create Invite Code"
        subtitle="Generate a new code for team access"
        maxWidth="max-w-md"
        footer={
          <>
            <Button variant="secondary" onClick={() => setShowCreateModal(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={isCreating || !newCode.trim()}>
              {isCreating ? 'Creating...' : 'Create Code'}
            </Button>
          </>
        }
      >
        <form onSubmit={handleCreate} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Code *</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newCode}
                onChange={(e) => { setNewCode(e.target.value); setCreateError('') }}
                placeholder="e.g. team-alpha-2024"
                autoFocus
                className="flex-1 px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
              />
              <Button type="button" variant="secondary" icon={Shuffle} onClick={generateRandomCode} className="shrink-0">
                Generate
              </Button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Label</label>
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="e.g. Alpha team access"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Daily Credits</label>
            <input
              type="number"
              min="1"
              value={newDailyCredits}
              onChange={(e) => setNewDailyCredits(e.target.value)}
              placeholder="250"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Expiry</label>
            <select
              value={newExpiryDuration}
              onChange={(e) => setNewExpiryDuration(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
            >
              {EXPIRY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {newExpiryDuration && (
              <p className="text-xs text-muted-foreground mt-1">
                Expires on {new Date(computeExpiryDate(newExpiryDuration)!).toLocaleDateString()}
              </p>
            )}
          </div>
          {createError && (
            <p className="text-sm text-red-500">{createError}</p>
          )}
        </form>
      </Modal>
    </div>
  )
}
