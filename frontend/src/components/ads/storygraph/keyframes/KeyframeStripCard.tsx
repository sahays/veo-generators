import { AlertOctagon, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Disclosure } from '@/components/ui/disclosure'
import type { KeyframeStripResponse } from '@/types/keyframes'
import { summarizeStrip } from './keyframeSummary'
import { KeyframeThumbRow } from './KeyframeThumbs'
import { KeyframeFrameRow, KeyframeVersionHistory } from './KeyframeFrameDetail'
import type { RegenMode } from './KeyframeRegenDialog'
import type { PendingRegen } from '@/hooks/useKeyframeBoard'

interface KeyframeStripCardProps {
  strip: KeyframeStripResponse
  canWrite: boolean
  isBusy: boolean
  pending: PendingRegen | null
  onAction: (strip: KeyframeStripResponse, t: number, mode: RegenMode) => void
}

const ManualEditBanner = () => (
  <div className="flex gap-2 rounded-lg border border-red-500/50 bg-red-500/10 p-2.5 text-xs text-red-300">
    <AlertOctagon size={14} className="mt-0.5 shrink-0" />
    <p>Automatic repair gave up on this clip. Review the flagged frames and use <strong>Edit…</strong> to give the keyframe director an instruction.</p>
  </div>
)

const StripTitle = ({ strip }: { strip: KeyframeStripResponse }) => (
  <span className="flex flex-wrap items-center gap-2">
    <span className="font-mono text-xs font-bold text-foreground">{strip.shot_id}</span>
    <span className="font-mono text-[10px] text-muted-foreground">{strip.scene_id} · clip {strip.clip_index}</span>
    {strip.set_id && <Badge variant="outline">v{strip.version}</Badge>}
    {strip.needs_manual_edit && <Badge variant="destructive">Needs manual edit</Badge>}
    {strip.stale && <Badge variant="warning"><Clock size={10} />Stale</Badge>}
  </span>
)

/** One clip's keyframe strip: collapsed thumbnails + summary, expandable per-frame detail. */
export const KeyframeStripCard = ({ strip, canWrite, isBusy, pending, onAction }: KeyframeStripCardProps) => {
  const summary = summarizeStrip(strip)
  const isPendingStrip = pending?.shotId === strip.shot_id
  return (
    <div className={cn('space-y-2 rounded-2xl border p-3', strip.needs_manual_edit ? 'border-red-500/60 bg-red-500/5 shadow-lg shadow-red-500/10' : 'border-border/70 bg-card/80')}>
      {strip.needs_manual_edit && <ManualEditBanner />}
      <Disclosure
        title={<StripTitle strip={strip} />}
        summary={<span className="text-[11px] text-muted-foreground">{summary.label}</span>}
        defaultOpen={strip.needs_manual_edit}
        contentClassName="space-y-3 pt-3"
      >
        <ol className="space-y-2">
          {strip.frames.map((f) => (
            <KeyframeFrameRow
              key={`${f.t}-${f.asset_id}`}
              frame={f}
              stale={strip.stale}
              canWrite={canWrite}
              isPending={isPendingStrip && pending?.t === f.t}
              isBusy={isBusy || pending !== null}
              onAction={(t, mode) => onAction(strip, t, mode)}
            />
          ))}
        </ol>
        <KeyframeVersionHistory versions={strip.versions} />
      </Disclosure>
      {strip.frames.length > 0 ? <KeyframeThumbRow frames={strip.frames} /> : <p className="text-[11px] text-muted-foreground">No keyframes derived for this clip yet.</p>}
    </div>
  )
}
