import { History, Loader2, PenLine, RefreshCw } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { KeyframeFrameView, KeyframeSetVersionView } from '@/types/keyframes'
import { parseSharedFrom } from './keyframeSummary'
import type { RegenMode } from './KeyframeRegenDialog'

/** Why per-frame actions are disabled for this frame, or `null` when allowed. */
export function frameLockReason(frame: KeyframeFrameView, stale: boolean): string | null {
  if (stale) return 'Keyframes are stale — regenerate S8_KEYFRAMES first.'
  const shared = frame.t === 0 ? parseSharedFrom(frame.shared_from) : null
  return shared ? `Shared start — edit ${shared.shotId}'s last frame (t${shared.t}) instead.` : null
}

export interface FrameActionsProps {
  frame: KeyframeFrameView
  lock: string | null
  isPending: boolean
  isBusy: boolean
  onAction: (t: number, mode: RegenMode) => void
}

/** Per-frame "Regenerate from here" / "Edit…" actions, disabled with a reason when locked. */
export const FrameActions = ({ frame, lock, isPending, isBusy, onAction }: FrameActionsProps) => (
  <div className="flex flex-wrap items-center gap-2">
    <Button variant="outline" size="xs" icon={isPending ? Loader2 : RefreshCw} disabled={lock !== null || isBusy} title={lock ?? undefined} onClick={() => onAction(frame.t, 'regenerate')}>
      Regenerate from here
    </Button>
    <Button variant="ghost" size="xs" icon={PenLine} disabled={lock !== null || isBusy} title={lock ?? undefined} onClick={() => onAction(frame.t, 'edit')}>
      Edit…
    </Button>
    {lock && <span className="text-[10px] text-muted-foreground">{lock}</span>}
  </div>
)

const formatWhen = (iso: string): string => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

/** Newest-first list of every keyframe set version for the clip. */
export const KeyframeVersionHistory = ({ versions }: { versions: KeyframeSetVersionView[] }) => {
  if (versions.length === 0) return null
  const ordered = [...versions].sort((a, b) => b.version - a.version)
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"><History size={12} />Version history</p>
      <ul className="space-y-1">
        {ordered.map((v) => (
          <li key={v.set_id} className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="font-mono font-bold text-foreground">v{v.version}</span>
            <Badge variant={v.status === 'active' ? 'success' : 'default'}>{v.status}</Badge>
            <span className="text-muted-foreground">{formatWhen(v.created_at)}</span>
            {v.reason && <span className="truncate text-muted-foreground">· {v.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
