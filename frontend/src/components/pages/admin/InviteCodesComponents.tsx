import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Ban,
  CalendarClock,
  Check,
  CheckCircle,
  Pencil,
  Shuffle,
  Trash2,
  X,
  Zap,
  ZapOff,
} from 'lucide-react'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/select'
import { Modal } from '@/components/Modal'
import { cn } from '@/lib/utils'

export interface InviteCode {
  id: string
  code: string
  label: string
  is_active: boolean
  is_power: boolean
  daily_credits: number
  expires_at: string | null
  createdAt: string
}

export const POWER_DEFAULT_DAYS = 14

export const EXPIRY_OPTIONS = [
  { value: '', label: 'No expiry' },
  { value: '1w', label: '1 week' },
  { value: '2w', label: '2 weeks' },
  { value: '1m', label: '1 month' },
  { value: '3m', label: '3 months' },
  { value: '6m', label: '6 months' },
]

export function computeExpiryDate(duration: string, from: Date = new Date()): string | null {
  if (!duration) return null
  const d = new Date(from)
  switch (duration) {
    case '1w':
      d.setDate(d.getDate() + 7)
      break
    case '2w':
      d.setDate(d.getDate() + 14)
      break
    case '1m':
      d.setMonth(d.getMonth() + 1)
      break
    case '3m':
      d.setMonth(d.getMonth() + 3)
      break
    case '6m':
      d.setMonth(d.getMonth() + 6)
      break
    default:
      return null
  }
  return d.toISOString()
}

const DailyLimitEditor = ({
  code,
  onSaveLimit,
}: {
  code: InviteCode
  onSaveLimit: (id: string, credits: number) => Promise<void>
}) => {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(String(code.daily_credits ?? 250))

  const submit = async () => {
    const val = parseInt(value, 10)
    if (isNaN(val) || val < 1) return
    await onSaveLimit(code.id, val)
    setEditing(false)
  }

  if (!editing) {
    return (
      <Button
        variant="unstyled"
        onClick={() => {
          setValue(String(code.daily_credits ?? 250))
          setEditing(true)
        }}
        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-blue-500/15 text-blue-600 dark:text-blue-400 hover:bg-blue-500/25 transition-colors"
      >
        {code.daily_credits ?? 250} credits/day
        <Pencil size={10} />
      </Button>
    )
  }

  return (
    <span className="inline-flex items-center gap-1">
      <Input
        type="number"
        min="1"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') submit()
          if (e.key === 'Escape') setEditing(false)
        }}
        autoFocus
        className="h-6 w-20 px-1.5 py-0.5 text-xs text-center"
      />
      <Button variant="ghost" size="icon" onClick={submit} className="h-6 w-6 text-green-500 hover:text-green-600">
        <Check size={14} />
      </Button>
      <Button variant="ghost" size="icon" onClick={() => setEditing(false)} className="h-6 w-6 text-muted-foreground hover:text-foreground">
        <X size={14} />
      </Button>
    </span>
  )
}

const InlineExtendBar = ({
  code,
  onExtend,
  onClose,
}: {
  code: InviteCode
  onExtend: (id: string, duration: string) => Promise<void>
  onClose: () => void
}) => {
  const [duration, setDuration] = useState('1m')
  const [saving, setSaving] = useState(false)

  const handleApply = async () => {
    setSaving(true)
    try {
      await onExtend(code.id, duration)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-2 mt-2">
      <NativeSelect value={duration} onChange={(e) => setDuration(e.target.value)} className="h-7 w-32 px-2 py-0.5 text-xs">
        {EXPIRY_OPTIONS.filter((o) => o.value).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
      <span className="text-[10px] text-muted-foreground">
        from{' '}
        {code.expires_at && new Date(code.expires_at) > new Date()
          ? new Date(code.expires_at).toLocaleDateString()
          : 'now'}
      </span>
      <Button variant="secondary" size="xs" onClick={handleApply} disabled={saving}>
        {saving ? 'Saving...' : 'Apply'}
      </Button>
      <Button variant="ghost" size="icon" onClick={onClose} className="h-6 w-6 text-muted-foreground hover:text-foreground">
        <X size={14} />
      </Button>
    </div>
  )
}

const InviteCodeActions = ({
  code,
  onPromote,
  onDemote,
  onToggleExtend,
  onRevoke,
  onActivate,
  onDelete,
}: {
  code: InviteCode
  onPromote: (id: string) => void
  onDemote: (id: string) => void
  onToggleExtend: () => void
  onRevoke: (id: string) => void
  onActivate: (id: string) => void
  onDelete: (id: string) => void
}) => (
  <div className="flex items-center gap-1">
    {code.is_power ? (
      <Button
        variant="ghost"
        icon={ZapOff}
        onClick={() => onDemote(code.id)}
        className="text-xs px-2 py-1 text-amber-600 hover:text-amber-700 dark:text-amber-400"
      >
        Remove Power
      </Button>
    ) : (
      <Button
        variant="ghost"
        icon={Zap}
        onClick={() => onPromote(code.id)}
        className="text-xs px-2 py-1 text-amber-600 hover:text-amber-700 dark:text-amber-400"
      >
        Make Power
      </Button>
    )}
    <Button variant="ghost" icon={CalendarClock} onClick={onToggleExtend} className="text-xs px-2 py-1">
      Extend
    </Button>
    {code.is_active ? (
      <Button variant="ghost" icon={Ban} onClick={() => onRevoke(code.id)} className="text-xs px-2 py-1">
        Revoke
      </Button>
    ) : (
      <Button variant="ghost" icon={CheckCircle} onClick={() => onActivate(code.id)} className="text-xs px-2 py-1">
        Activate
      </Button>
    )}
    <Button
      variant="ghost"
      icon={Trash2}
      onClick={() => onDelete(code.id)}
      className="text-xs px-2 py-1 text-red-500 hover:text-red-600"
    >
      Delete
    </Button>
  </div>
)

export const InviteCodeRow = ({
  code,
  onSaveLimit,
  onExtend,
  onPromote,
  onDemote,
  onRevoke,
  onActivate,
  onDelete,
}: {
  code: InviteCode
  onSaveLimit: (id: string, credits: number) => Promise<void>
  onExtend: (id: string, duration: string) => Promise<void>
  onPromote: (id: string) => void
  onDemote: (id: string) => void
  onRevoke: (id: string) => void
  onActivate: (id: string) => void
  onDelete: (id: string) => void
}) => {
  const [isExtending, setIsExtending] = useState(false)
  const isExpired = Boolean(code.expires_at && new Date(code.expires_at) < new Date())
  const isActive = code.is_active && !isExpired

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass bg-card rounded-xl border border-border p-4 flex items-center justify-between gap-4"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <code className="text-sm font-mono font-bold text-foreground">{code.code}</code>
          <span
            className={cn(
              'text-xs px-2 py-0.5 rounded-full font-medium',
              isActive
                ? 'bg-green-500/15 text-green-600 dark:text-green-400'
                : 'bg-red-500/15 text-red-600 dark:text-red-400',
            )}
          >
            {isExpired ? 'Expired' : isActive ? 'Active' : 'Revoked'}
          </span>
          {code.is_power && (
            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium bg-amber-500/15 text-amber-600 dark:text-amber-400">
              <Zap size={10} className="fill-current" />
              Power
            </span>
          )}
          <DailyLimitEditor code={code} onSaveLimit={onSaveLimit} />
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
        {isExtending && (
          <InlineExtendBar code={code} onExtend={onExtend} onClose={() => setIsExtending(false)} />
        )}
      </div>
      <InviteCodeActions
        code={code}
        onPromote={onPromote}
        onDemote={onDemote}
        onToggleExtend={() => setIsExtending((v) => !v)}
        onRevoke={onRevoke}
        onActivate={onActivate}
        onDelete={onDelete}
      />
    </motion.div>
  )
}
