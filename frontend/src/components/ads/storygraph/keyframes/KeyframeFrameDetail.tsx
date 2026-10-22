import { History, Link2, Loader2, PenLine, RefreshCw, UserPen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { KeyframeFrameView, KeyframeSetVersionView } from '@/types/keyframes'
import { parseSharedFrom } from './keyframeSummary'
import { KeyframeStatusBadge } from './KeyframeThumbs'
import type { RegenMode } from './KeyframeRegenDialog'

/** Why per-frame actions are disabled for this frame, or `null` when allowed. */
export function frameLockReason(frame: KeyframeFrameView, stale: boolean): string | null {
  if (stale) return 'Keyframes are stale — regenerate S8_KEYFRAMES first.'
  const shared = frame.t === 0 ? parseSharedFrom(frame.shared_from) : null
  return shared ? `Shared start — edit ${shared.shotId}'s last frame (t${shared.t}) instead.` : null
}

interface KeyframeFrameRowProps {
  frame: KeyframeFrameView
  stale: boolean
  canWrite: boolean
  isPending: boolean
  isBusy: boolean
  onAction: (t: number, mode: RegenMode) => void
}

const FrameMeta = ({ frame }: { frame: KeyframeFrameView }) => (
  <div className="flex flex-wrap items-center gap-1.5">
    <span className="font-mono text-xs font-bold text-foreground">t{frame.t}</span>
    <KeyframeStatusBadge status={frame.status} />
    {frame.shared_from && <Badge variant="indigo"><Link2 size={10} />Shared from {frame.shared_from}</Badge>}
    {frame.edited_by === 'human' && <Badge variant="steel"><UserPen size={10} />Human edit</Badge>}
    <span className="font-mono text-[10px] text-muted-foreground">{frame.attempts} attempt{frame.attempts === 1 ? '' : 's'}</span>
  </div>
)

const FrameActions = ({ frame, lock, isPending, isBusy, onAction }: { frame: KeyframeFrameView; lock: string | null; isPending: boolean; isBusy: boolean; onAction: KeyframeFrameRowProps['onAction'] }) => (
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

/** Expanded detail for one keyframe: image, t label, status, issues, state caption, actions. */
export const KeyframeFrameRow = ({ frame, stale, canWrite, isPending, isBusy, onAction }: KeyframeFrameRowProps) => (
  <li className={cn('flex flex-col gap-3 rounded-xl border p-3 sm:flex-row', frame.status === 'manual_edit' ? 'border-red-500/50 bg-red-500/5' : 'border-border/60 bg-card/60')}>
    <img src={frame.url} alt={`Keyframe t${frame.t}`} loading="lazy" className="aspect-video w-full shrink-0 rounded-lg bg-black object-cover sm:w-44" />
    <div className="min-w-0 flex-1 space-y-2">
      <FrameMeta frame={frame} />
      {frame.state_summary && <p className="text-xs text-muted-foreground">{frame.state_summary}</p>}
      {frame.issues.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-amber-400">
          {frame.issues.map((issue) => <li key={issue}>{issue}</li>)}
        </ul>
      )}
      {canWrite && <FrameActions frame={frame} lock={frameLockReason(frame, stale)} isPending={isPending} isBusy={isBusy} onAction={onAction} />}
    </div>
  </li>
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
