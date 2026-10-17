import { useState, useEffect, useCallback } from 'react'
import { Shield, Plus, Shuffle } from 'lucide-react'
import { Button } from '@/components/Common'
import { Modal } from '@/components/Modal'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/select'
import { api } from '@/hooks/useApiClient'
import {
  InviteCodeRow,
  EXPIRY_OPTIONS,
  computeExpiryDate,
  type InviteCode,
} from './InviteCodesComponents'

function generateRandomInviteString(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  const array = new Uint8Array(16)
  crypto.getRandomValues(array)
  for (let i = 0; i < 16; i++) result += chars[array[i] % chars.length]
  return result
}

const CreateInviteCodeFormFields = ({
  newCode,
  setNewCode,
  newLabel,
  setNewLabel,
  newDailyCredits,
  setNewDailyCredits,
  newExpiryDuration,
  setNewExpiryDuration,
  createError,
  setCreateError,
}: {
  newCode: string
  setNewCode: (v: string) => void
  newLabel: string
  setNewLabel: (v: string) => void
  newDailyCredits: string
  setNewDailyCredits: (v: string) => void
  newExpiryDuration: string
  setNewExpiryDuration: (v: string) => void
  createError: string
  setCreateError: (v: string) => void
}) => (
  <>
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">Code *</label>
      <div className="flex gap-2">
        <Input
          type="text"
          value={newCode}
          onChange={(e) => {
            setNewCode(e.target.value)
            setCreateError('')
          }}
          placeholder="e.g. team-alpha-2024"
          autoFocus
          className="flex-1"
        />
        <Button
          type="button"
          variant="secondary"
          icon={Shuffle}
          onClick={() => {
            setNewCode(generateRandomInviteString())
            setCreateError('')
          }}
          className="shrink-0"
        >
          Generate
        </Button>
      </div>
    </div>
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">Label</label>
      <Input type="text" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="e.g. Alpha team access" />
    </div>
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">Daily Credits</label>
      <Input type="number" min="1" value={newDailyCredits} onChange={(e) => setNewDailyCredits(e.target.value)} placeholder="250" />
    </div>
    <div>
      <label className="block text-sm font-medium text-foreground mb-1">Expiry</label>
      <NativeSelect value={newExpiryDuration} onChange={(e) => setNewExpiryDuration(e.target.value)}>
        {EXPIRY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </NativeSelect>
      {newExpiryDuration && (
        <p className="text-xs text-muted-foreground mt-1">
          Expires on {new Date(computeExpiryDate(newExpiryDuration)!).toLocaleDateString()}
        </p>
      )}
    </div>
    {createError && <p className="text-sm text-red-500">{createError}</p>}
  </>
)

function buildInvitePayload(newCode: string, newLabel: string, newDailyCredits: string, newExpiryDuration: string) {
  const data: { code: string; label?: string; daily_credits?: number; expires_at?: string } = { code: newCode.trim() }
  if (newLabel.trim()) data.label = newLabel.trim()
  const credits = parseInt(newDailyCredits, 10)
  if (!isNaN(credits) && credits > 0) data.daily_credits = credits
  const expiryDate = computeExpiryDate(newExpiryDuration)
  if (expiryDate) data.expires_at = expiryDate
  return data
}

const CreateInviteCodeModal = ({
  isOpen,
  onClose,
  onCreate,
}: {
  isOpen: boolean
  onClose: () => void
  onCreate: (payload: { code: string; label?: string; daily_credits?: number; expires_at?: string }) => Promise<void>
}) => {
  const [newCode, setNewCode] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [newDailyCredits, setNewDailyCredits] = useState('250')
  const [newExpiryDuration, setNewExpiryDuration] = useState('')
  const [createError, setCreateError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!newCode.trim()) return
    setIsCreating(true)
    setCreateError('')
    try {
      await onCreate(buildInvitePayload(newCode, newLabel, newDailyCredits, newExpiryDuration))
      setNewCode('')
      setNewLabel('')
      setNewDailyCredits('250')
      setNewExpiryDuration('')
      onClose()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create code')
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => { setCreateError(''); onClose() }}
      title="Create Invite Code"
      subtitle="Generate a new code for team access"
      maxWidth="max-w-md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => handleSubmit()} disabled={isCreating || !newCode.trim()}>
            {isCreating ? 'Creating...' : 'Create Code'}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <CreateInviteCodeFormFields newCode={newCode} setNewCode={setNewCode} newLabel={newLabel} setNewLabel={setNewLabel} newDailyCredits={newDailyCredits} setNewDailyCredits={setNewDailyCredits} newExpiryDuration={newExpiryDuration} setNewExpiryDuration={setNewExpiryDuration} createError={createError} setCreateError={setCreateError} />
      </form>
    </Modal>
  )
}

function useInviteCodesController() {
  const [codes, setCodes] = useState<InviteCode[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const fetchCodes = useCallback(async () => {
    try {
      const data = await api.auth.listCodes()
      setCodes(data as unknown as InviteCode[])
    } catch {
      // ignore error
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCodes()
  }, [fetchCodes])

  const handleExtend = async (id: string, duration: string) => {
    const expiresAt = computeExpiryDate(duration)
    await api.auth.updateCode(id, { expires_at: expiresAt })
    fetchCodes()
  }

  const handleSaveLimit = async (id: string, credits: number) => {
    if (isNaN(credits) || credits <= 0) return
    await api.auth.updateCode(id, { daily_credits: credits }).catch(() => {})
    fetchCodes()
  }

  return { codes, isLoading, fetchCodes, handleExtend, handleSaveLimit }
}

function createRoleAndLifecycleHandlers(fetchCodes: () => void) {
  return {
    handleRevoke: async (id: string) => { await api.auth.revokeCode(id); fetchCodes() },
    handleActivate: async (id: string) => { await api.auth.activateCode(id); fetchCodes() },
    handlePromote: async (id: string) => { await api.auth.promoteCode(id).catch(() => {}); fetchCodes() },
    handleDemote: async (id: string) => { await api.auth.demoteCode(id).catch(() => {}); fetchCodes() },
    handleDelete: async (id: string) => {
      if (!confirm('Permanently delete this invite code?')) return
      await api.auth.deleteCode(id)
      fetchCodes()
    },
  }
}

export const InviteCodesPage = () => {
  const { codes, isLoading, fetchCodes, handleExtend, handleSaveLimit } = useInviteCodesController()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const actions = createRoleAndLifecycleHandlers(fetchCodes)

  if (isLoading) {
    return <div className="flex items-center justify-center py-20"><div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3"><Shield size={24} className="text-accent" /><h1 className="text-2xl font-heading font-bold text-foreground">Invite Codes</h1></div>
        <Button icon={Plus} onClick={() => setShowCreateModal(true)}>New Code</Button>
      </div>
      {codes.length === 0 ? (
        <div className="glass bg-card rounded-xl p-12 text-center"><p className="text-muted-foreground">No invite codes yet. Create one to get started.</p></div>
      ) : (
        <div className="space-y-3">
          {codes.map((code) => (
            <InviteCodeRow key={code.id} code={code} onSaveLimit={handleSaveLimit} onExtend={handleExtend} onPromote={actions.handlePromote} onDemote={actions.handleDemote} onRevoke={actions.handleRevoke} onActivate={actions.handleActivate} onDelete={actions.handleDelete} />
          ))}
        </div>
      )}
      <CreateInviteCodeModal isOpen={showCreateModal} onClose={() => setShowCreateModal(false)} onCreate={async (data) => { await api.auth.createCode(data); fetchCodes() }} />
    </div>
  )
}

