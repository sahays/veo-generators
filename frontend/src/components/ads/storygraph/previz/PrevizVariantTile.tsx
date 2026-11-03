import { CheckCircle2, Loader2, Star } from 'lucide-react'
import { Badge, Button } from '@/components/Common'
import { Disclosure } from '@/components/ui/disclosure'
import type { PrevizRestyleVariant, PrevizVariant } from '@/types/previz'
import { JOB_STATUS_META, VARIANT_LABEL } from './previzLogic'
import { FailureBanner, LazyVideo, ToneBadge } from './PrevizMedia'

export interface PrevizVariantTileProps {
  shotId: string
  kind: PrevizRestyleVariant
  variant: PrevizVariant | undefined
  canWrite: boolean
  isPromoting: boolean
  isBusy: boolean
  onPromote: (kind: PrevizRestyleVariant) => void
}

const FrameStrip = ({ urls, shotId }: { urls: string[]; shotId: string }) => (
  <Disclosure
    title={<span className="text-xs text-muted-foreground">Restyled keyframes</span>}
    summary={<span className="text-[11px] tabular-nums text-muted-foreground">{urls.length}</span>}
    triggerClassName="py-1"
    contentClassName="flex gap-1.5 overflow-x-auto pb-1 pt-1 scrollbar-thin"
  >
    {urls.map((url, i) => (
      <figure key={url} className="relative h-14 w-24 shrink-0 overflow-hidden rounded-md bg-muted ring-1 ring-border/60">
        <img src={url} alt={`${shotId} restyled keyframe ${i}`} loading="lazy" decoding="async" className="h-full w-full object-cover" />
        <figcaption className="absolute bottom-0 left-0 rounded-tr bg-black/70 px-1 font-mono text-[9px] text-white">t{i}</figcaption>
      </figure>
    ))}
  </Disclosure>
)

const PromoteAction = ({ variant, kind, canWrite, isPromoting, isBusy, onPromote }: Omit<PrevizVariantTileProps, 'shotId' | 'variant'> & { variant: PrevizVariant }) => {
  if (variant.promoted) return <Badge variant="success"><CheckCircle2 size={11} aria-hidden />In use</Badge>
  if (!canWrite || variant.status !== 'done' || !variant.video_url) return null
  return (
    <Button variant="outline" size="xs" icon={isPromoting ? Loader2 : Star} disabled={isBusy} onClick={() => onPromote(kind)}>
      Use this render
    </Button>
  )
}

/** One restyle variant (E1 or E2) of a shot: video, status, failure reason, promote. */
export const PrevizVariantTile = (props: PrevizVariantTileProps) => {
  const { shotId, kind, variant } = props
  const meta = variant ? JOB_STATUS_META[variant.status] : null
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex min-h-7 items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-foreground">{VARIANT_LABEL[kind]}</p>
        <div className="flex items-center gap-1.5">
          {meta && <ToneBadge tone={meta.tone} label={meta.label} />}
          {variant && <PromoteAction {...props} variant={variant} />}
        </div>
      </div>
      <LazyVideo src={variant?.video_url ?? null} label={`${shotId} ${VARIANT_LABEL[kind]}`} />
      {variant?.status === 'failed' && <FailureBanner reason={variant.failure_reason} />}
      {kind === 'E2_keyframe_restyle' && variant && variant.frame_urls.length > 0 && <FrameStrip urls={variant.frame_urls} shotId={shotId} />}
    </div>
  )
}
