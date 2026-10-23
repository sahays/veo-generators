import { useState } from 'react'
import { Maximize2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import type { KeyframeFrameView } from '@/types/keyframes'
import { FrameActions, frameLockReason } from './KeyframeFrameDetail'
import { FrameChips, KeyframeFrameCommentary } from './KeyframeFrameCommentary'
import type { RegenMode } from './KeyframeRegenDialog'

export interface KeyframeFrameCardProps {
  shotId: string
  frame: KeyframeFrameView
  stale: boolean
  canWrite: boolean
  isPending: boolean
  isBusy: boolean
  onAction: (t: number, mode: RegenMode) => void
}

const CARD_TONE: Record<KeyframeFrameView['status'], string> = {
  approved: 'ring-border/60',
  needs_review: 'ring-amber-500/40',
  manual_edit: 'ring-red-500/50',
}

/** Lazy image at its natural aspect (16:9 or the project orientation), skeleton until decoded. */
const FrameImage = ({ frame, onOpen }: { frame: KeyframeFrameView; onOpen: () => void }) => {
  const [loaded, setLoaded] = useState(false)
  return (
    <Button variant="unstyled" size="none" onClick={onOpen} aria-label={`Enlarge keyframe t=${frame.t}s`} className="group relative block w-full overflow-hidden bg-black">
      {!loaded && <Skeleton className="aspect-video w-full rounded-none" />}
      <img
        src={frame.url} alt={`Keyframe t=${frame.t}s`} loading="lazy" decoding="async" onLoad={() => setLoaded(true)}
        className={cn('mx-auto h-auto max-h-[26rem] w-full object-contain transition-transform duration-300 group-hover:scale-[1.02]', !loaded && 'absolute inset-0 opacity-0')}
      />
      <span className="absolute right-2 top-2 rounded-md bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100" aria-hidden><Maximize2 size={14} /></span>
    </Button>
  )
}

const FrameLightbox = ({ shotId, frame, open, onClose }: { shotId: string; frame: KeyframeFrameView; open: boolean; onClose: () => void }) => (
  <Modal isOpen={open} onClose={onClose} title={`${shotId} · t=${frame.t}s`} subtitle="S8_KEYFRAMES · keyframe" maxWidth="max-w-5xl">
    <div className="space-y-4">
      <img src={frame.url} alt={`Keyframe t=${frame.t}s, enlarged`} className="mx-auto max-h-[70vh] w-auto rounded-lg bg-black object-contain" />
      <FrameChips frame={frame} />
    </div>
  </Modal>
)

/** Large keyframe card: full-width image (click to enlarge) with commentary and actions below. */
export const KeyframeFrameCard = ({ shotId, frame, stale, canWrite, isPending, isBusy, onAction }: KeyframeFrameCardProps) => {
  const [open, setOpen] = useState(false)
  return (
    <li className={cn('flex flex-col overflow-hidden rounded-xl bg-card shadow-sm ring-1', CARD_TONE[frame.status])}>
      <FrameImage frame={frame} onOpen={() => setOpen(true)} />
      <div className="flex flex-1 flex-col gap-3 p-3">
        <KeyframeFrameCommentary frame={frame} />
        {canWrite && (
          <div className="mt-auto border-t border-border/50 pt-2.5">
            <FrameActions frame={frame} lock={frameLockReason(frame, stale)} isPending={isPending} isBusy={isBusy} onAction={onAction} />
          </div>
        )}
      </div>
      <FrameLightbox shotId={shotId} frame={frame} open={open} onClose={() => setOpen(false)} />
    </li>
  )
}
