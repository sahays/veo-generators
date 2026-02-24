import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Shield, Trash2, Ban, CheckCircle, Shuffle } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/Common'
import { Modal } from '@/components/Modal'
import { cn } from '@/lib/utils'

interface InviteCode {
  id: string
  code: string
  label: string
  is_active: boolean
  expires_at: string | null
  createdAt: string
}

export const InviteCodesPage = () => {
  const [codes, setCodes] = useState<InviteCode[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newCode, setNewCode] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newExpiry, setNewExpiry] = useState('')
  const [createError, setCreateError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

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
      const data: { code: string; label?: string; expires_at?: string } = { code: newCode.trim() }
      if (newLabel.trim()) data.label = newLabel.trim()
      if (newExpiry) data.expires_at = new Date(newExpiry).toISOString()
      await api.auth.createCode(data)
      setShowCreateModal(false)
      setNewCode('')
      setNewLabel('')
      setNewExpiry('')
      fetchCodes()
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create code')
    } finally {
      setIsCreating(false)
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

            return (
              <motion.div
                key={code.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="glass bg-card rounded-xl border border-border p-4 flex items-center justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-sm font-mono font-bold text-foreground">{code.code}</code>
                    <span className={cn(
                      "text-xs px-2 py-0.5 rounded-full font-medium",
                      isActive
                        ? "bg-green-500/15 text-green-600 dark:text-green-400"
                        : "bg-red-500/15 text-red-600 dark:text-red-400"
                    )}>
                      {isExpired ? 'Expired' : isActive ? 'Active' : 'Revoked'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {code.label && <span>{code.label}</span>}
                    {code.expires_at && (
                      <span>Expires: {new Date(code.expires_at).toLocaleDateString()}</span>
                    )}
                    <span>Created: {new Date(code.createdAt).toLocaleDateString()}</span>
                  </div>
                </div>

                <div className="flex items-center gap-1">
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
            <label className="block text-sm font-medium text-foreground mb-1">Expiry Date</label>
            <input
              type="date"
              value={newExpiry}
              onChange={(e) => setNewExpiry(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm"
            />
          </div>
          {createError && (
            <p className="text-sm text-red-500">{createError}</p>
          )}
        </form>
      </Modal>
    </div>
  )
}
