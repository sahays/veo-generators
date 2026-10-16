import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Shield, Trash2, Ban, CheckCircle, Shuffle, Pencil, Check, X, CalendarClock, Zap, ZapOff } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/select'
import { Modal } from '@/components/Modal'
import { cn } from '@/lib/utils'

interface InviteCode {
  id: string
  code: string
  label: string
  is_active: boolean
  is_power: boolean
  daily_credits: number
  expires_at: string | null
  createdAt: string
}

// Default validity granted on promotion (mirrors POWER_DEFAULT_DAYS on the API).
const POWER_DEFAULT_DAYS = 14

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

  const handlePromote = async (id: string) => {
    if (!confirm(`Promote to power user? Grants full access to every feature except invite codes, with a default ${POWER_DEFAULT_DAYS}-day expiry (extendable below).`)) return
    try {
      await api.auth.promoteCode(id)
      fetchCodes()
    } catch (err) {
      console.error('Failed to promote code', err)
    }
  }

  const handleDemote = async (id: string) => {
    if (!confirm('Remove power-user access? The code stays active as a regular guest with its current expiry.')) return
    try {
      await api.auth.demoteCode(id)
      fetchCodes()
    } catch (err) {
      console.error('Failed to demote code', err)
    }
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
                    {code.is_power && (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-500/15 text-amber-600 dark:text-amber-400">
                        <Zap size={10} className="fill-current" />
                        Power
                      </span>
                    )}
                    {isEditingLimit ? (
                      <span className="inline-flex items-center gap-1">
                        <Input
                          type="number"
                          min="1"
                          value={editingLimitValue}
                          onChange={(e) => setEditingLimitValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveDailyCredits(code.id)
                            if (e.key === 'Escape') setEditingLimitId(null)
                          }}
                          autoFocus
                          className="h-6 w-20 px-1.5 py-0.5 text-xs text-center"
                        />
                        <Button variant="ghost" size="icon" onClick={() => handleSaveDailyCredits(code.id)} className="h-6 w-6 text-green-500 hover:text-green-600">
                          <Check size={14} />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => setEditingLimitId(null)} className="h-6 w-6 text-muted-foreground hover:text-foreground">
                          <X size={14} />
                        </Button>
                      </span>
                    ) : (
                      <Button
                        variant="unstyled"
                        onClick={() => { setEditingLimitId(code.id); setEditingLimitValue(String(code.daily_credits ?? 250)) }}
                        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-blue-500/15 text-blue-600 dark:text-blue-400 hover:bg-blue-500/25 transition-colors"
                      >
                        {code.daily_credits ?? 250} credits/day
                        <Pencil size={10} />
                      </Button>
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
                      <NativeSelect
                        value={extendDuration}
                        onChange={(e) => setExtendDuration(e.target.value)}
                        className="h-7 w-32 px-2 py-0.5 text-xs"
                      >
                        {EXPIRY_OPTIONS.filter(o => o.value).map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </NativeSelect>
                      <span className="text-[10px] text-muted-foreground">
                        from {code.expires_at && new Date(code.expires_at) > new Date()
                          ? new Date(code.expires_at).toLocaleDateString()
                          : 'now'}
                      </span>
                      <Button
                        variant="secondary"
                        size="xs"
                        onClick={() => handleExtend(code.id)}
                        disabled={isExtending}
                      >
                        {isExtending ? 'Saving...' : 'Apply'}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setExtendingId(null)}
                        className="h-6 w-6 text-muted-foreground hover:text-foreground"
                      >
                        <X size={14} />
                      </Button>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  {code.is_power ? (
                    <Button
                      variant="ghost"
                      icon={ZapOff}
                      onClick={() => handleDemote(code.id)}
                      className="text-xs px-2 py-1 text-amber-600 hover:text-amber-700 dark:text-amber-400"
                    >
                      Remove Power
                    </Button>
                  ) : (
                    <Button
                      variant="ghost"
                      icon={Zap}
                      onClick={() => handlePromote(code.id)}
                      className="text-xs px-2 py-1 text-amber-600 hover:text-amber-700 dark:text-amber-400"
                    >
                      Make Power
                    </Button>
                  )}
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
              <Input
                type="text"
                value={newCode}
                onChange={(e) => { setNewCode(e.target.value); setCreateError('') }}
                placeholder="e.g. team-alpha-2024"
                autoFocus
                className="flex-1"
              />
              <Button type="button" variant="secondary" icon={Shuffle} onClick={generateRandomCode} className="shrink-0">
                Generate
              </Button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Label</label>
            <Input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="e.g. Alpha team access"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Daily Credits</label>
            <Input
              type="number"
              min="1"
              value={newDailyCredits}
              onChange={(e) => setNewDailyCredits(e.target.value)}
              placeholder="250"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Expiry</label>
            <NativeSelect
              value={newExpiryDuration}
              onChange={(e) => setNewExpiryDuration(e.target.value)}
            >
              {EXPIRY_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </NativeSelect>
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
