import type { ReactNode } from 'react'
import { AlertOctagon, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Disclosure } from '@/components/ui/disclosure'
import type { KeyframeStripResponse } from '@/types/keyframes'
import { stripStatus, summarizeStrip, type StripSummary } from './keyframeSummary'
import { KeyframeVersionHistory } from './KeyframeFrameDetail'
import { KeyframeFrameCard } from './KeyframeFrameCard'
import type { RegenMode } from './KeyframeRegenDialog'
import type { PendingRegen } from '@/hooks/useKeyframeBoard'

interface KeyframeStripCardProps {
  strip: KeyframeStripResponse
  canWrite: boolean
  isBusy: boolean
  pending: PendingRegen | null
  onAction: (strip: KeyframeStripResponse, t: number, mode: RegenMode) => void
}

const Banner = ({ children }: { children: ReactNode }) => (
  <div role="alert" className="flex gap-2 rounded-lg border border-red-500/50 bg-red-500/10 p-2.5 text-xs text-red-600 dark:text-red-300">
    <AlertOctagon size={14} className="mt-0.5 shrink-0" aria-hidden />
    <p>{children}</p>
  </div>
)

const StripBanner = ({ strip }: { strip: KeyframeStripResponse }) => {
  if (strip.failure_reason) {
    return <Banner>Keyframe derivation failed for this clip: <span className="font-mono">{strip.failure_reason}</span>. Use Resume keyframes to retry only the failed clips.</Banner>
  }
  if (!strip.needs_manual_edit) return null
  return <Banner>Automatic repair gave up on this clip. Review the flagged frames and use <strong>Edit…</strong> to give the keyframe director an instruction.</Banner>
}

const StripTitle = ({ strip, summary }: { strip: KeyframeStripResponse; summary: StripSummary }) => {
  const status = stripStatus(strip, summary)
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-sm font-semibold text-foreground">{strip.shot_id}</span>
      <span className="font-mono text-[11px] text-muted-foreground">{strip.scene_id} · clip {strip.clip_index}</span>
      {strip.set_id && <Badge variant="outline">v{strip.version}</Badge>}
      {status && <Badge variant={status.tone}>{status.label}</Badge>}
      {strip.stale && <Badge variant="warning"><Clock size={10} aria-hidden />Stale</Badge>}
    </span>
  )
}

/** 3 per row on desktop, 2 on tablet, 1 on mobile. */
const FrameGrid = ({ strip, canWrite, isBusy, pending, onAction }: KeyframeStripCardProps) => {
  if (strip.frames.length === 0) return <p className="text-[11px] text-muted-foreground">No keyframes derived for this clip yet.</p>
  const isPendingStrip = pending?.shotId === strip.shot_id
  return (
    <ol className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {strip.frames.map((f) => (
        <KeyframeFrameCard
          key={`${f.t}-${f.asset_id}`} shotId={strip.shot_id} frame={f} stale={strip.stale} canWrite={canWrite}
          isPending={isPendingStrip && pending?.t === f.t} isBusy={isBusy || pending !== null}
          onAction={(t, mode) => onAction(strip, t, mode)}
        />
      ))}
    </ol>
  )
}

/** One clip: section header + banners, then a responsive grid of large per-second keyframe cards. */
export const KeyframeStripCard = (props: KeyframeStripCardProps) => {
  const { strip } = props
  const summary = summarizeStrip(strip)
  const attention = strip.needs_manual_edit || Boolean(strip.failure_reason)
  return (
    <section className={cn('space-y-3 rounded-2xl border p-3 sm:p-4', attention ? 'border-red-500/60 bg-red-500/5' : 'border-border/70 bg-card/80')}>
      <StripBanner strip={strip} />
      <Disclosure
        title={<StripTitle strip={strip} summary={summary} />}
        summary={<span className="text-[11px] text-muted-foreground">{summary.label}</span>}
        defaultOpen
        contentClassName="space-y-4 pt-3"
      >
        <FrameGrid {...props} />
        {strip.versions.length > 0 && (
          <Disclosure title={<span className="text-xs text-muted-foreground">Version history</span>} triggerClassName="py-1" contentClassName="pt-1">
            <KeyframeVersionHistory versions={strip.versions} />
          </Disclosure>
        )}
      </Disclosure>
    </section>
  )
}
