import { Link2, UserPen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import type { KeyframeFrameStatus, KeyframeFrameView } from '@/types/keyframes'
import { FRAME_STATUS_META } from './keyframeSummary'

export const KeyframeStatusBadge = ({ status }: { status: KeyframeFrameStatus }) => {
  const meta = FRAME_STATUS_META[status]
  return <Badge variant={meta.tone}>{meta.label}</Badge>
}

const STATUS_RING: Record<KeyframeFrameStatus, string> = {
  approved: 'ring-emerald-500/40',
  needs_review: 'ring-amber-400/70',
  manual_edit: 'ring-red-500/80',
}

/** Small t-labelled thumbnail; status is conveyed by the ring and the hover title. */
export const KeyframeThumb = ({ frame }: { frame: KeyframeFrameView }) => (
  <figure
    className={cn('relative w-16 shrink-0 aspect-video overflow-hidden rounded-md bg-black ring-1', STATUS_RING[frame.status])}
    title={`t${frame.t} · ${FRAME_STATUS_META[frame.status].label}${frame.state_summary ? ` — ${frame.state_summary}` : ''}`}
  >
    <img src={frame.url} alt={`Keyframe t${frame.t}`} loading="lazy" className="h-full w-full object-cover" />
    <figcaption className="absolute bottom-0 left-0 rounded-tr bg-black/70 px-1 font-mono text-[9px] text-white">t{frame.t}</figcaption>
    {frame.shared_from && <Link2 size={10} className="absolute right-0.5 top-0.5 text-sky-300 drop-shadow" aria-label="Shared from previous clip" />}
    {frame.edited_by === 'human' && <UserPen size={10} className="absolute left-0.5 top-0.5 text-orange-300 drop-shadow" aria-label="Edited by a human" />}
  </figure>
)

/** Collapsed view: compact horizontal row of every keyframe t=0..N. */
export const KeyframeThumbRow = ({ frames }: { frames: KeyframeFrameView[] }) => (
  <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
    {frames.map((f) => <KeyframeThumb key={`${f.t}-${f.asset_id}`} frame={f} />)}
  </div>
)
