import { Box, Timer } from 'lucide-react'
import type { PrevizRestyleVariant, ShotPreviz } from '@/types/previz'
import type { PendingPromote } from '@/hooks/usePrevizBoard'
import { JOB_STATUS_META, RESTYLE_VARIANTS, variantsByKind } from './previzLogic'
import { FailureBanner, LazyVideo, ToneBadge } from './PrevizMedia'
import { PrevizVariantTile } from './PrevizVariantTile'

export interface PrevizShotCardProps {
  shot: ShotPreviz
  canWrite: boolean
  isBusy: boolean
  pendingPromote: PendingPromote | null
  onPromote: (shot: ShotPreviz, kind: PrevizRestyleVariant) => void
}

const ShotHeader = ({ shot }: { shot: ShotPreviz }) => {
  const meta = JOB_STATUS_META[shot.status]
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
        <span className="truncate font-mono text-xs">{shot.shot_id}</span>
        <span className="text-xs text-muted-foreground">Clip {shot.clip_index + 1}</span>
      </p>
      <div className="flex items-center gap-2">
        {shot.render_seconds !== null && (
          <span className="flex items-center gap-1 text-[11px] tabular-nums text-muted-foreground" title="Blender render time">
            <Timer size={11} aria-hidden />{shot.render_seconds.toFixed(1)}s
          </span>
        )}
        <ToneBadge tone={meta.tone} label={meta.label} />
      </div>
    </div>
  )
}

/** One shot: greybox previz first, then E1 / E2 restyles side by side when present. */
export const PrevizShotCard = ({ shot, canWrite, isBusy, pendingPromote, onPromote }: PrevizShotCardProps) => {
  const byKind = variantsByKind(shot)
  const present = RESTYLE_VARIANTS.filter((k) => byKind[k] !== undefined)
  return (
    <article className="space-y-3 rounded-xl bg-background/60 p-3 shadow-sm ring-1 ring-border/60">
      <ShotHeader shot={shot} />
      {shot.status === 'failed' && <FailureBanner reason={shot.failure_reason} />}
      <div className={present.length > 0 ? 'grid gap-3 lg:grid-cols-3' : 'grid gap-3 md:max-w-xl'}>
        <div className="min-w-0 space-y-2">
          <p className="flex min-h-7 items-center gap-1.5 text-xs font-medium text-foreground"><Box size={12} aria-hidden />Greybox previz</p>
          <LazyVideo src={shot.previz_video_url} label={`${shot.shot_id} greybox previz`} />
        </div>
        {present.map((kind) => (
          <PrevizVariantTile
            key={kind} shotId={shot.shot_id} kind={kind} variant={byKind[kind]} canWrite={canWrite} isBusy={isBusy}
            isPromoting={pendingPromote?.shotId === shot.shot_id && pendingPromote.variant === kind}
            onPromote={(k) => onPromote(shot, k)}
          />
        ))}
      </div>
    </article>
  )
}
