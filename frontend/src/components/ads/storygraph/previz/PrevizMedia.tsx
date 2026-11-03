import { AlertTriangle, Film } from 'lucide-react'
import { Badge } from '@/components/Common'
import { cn } from '@/lib/utils'
import type { PrevizTone } from './previzLogic'

/**
 * Lazy video: `preload="none"` so nothing is fetched until the user presses play
 * (a board can hold dozens of clips; the studio page must stay snappy).
 */
export const LazyVideo = ({ src, label, className }: { src: string | null; label: string; className?: string }) => (
  <div className={cn('relative aspect-video w-full overflow-hidden rounded-lg bg-black/80 ring-1 ring-border/60', className)}>
    {src ? (
      <video src={src} controls preload="none" playsInline aria-label={label} className="h-full w-full object-contain" />
    ) : (
      <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-foreground">
        <Film size={18} aria-hidden />
        <span className="text-[11px]">No render yet</span>
      </div>
    )}
  </div>
)

export const ToneBadge = ({ tone, label }: { tone: PrevizTone; label: string }) => (
  <Badge variant={tone}>{label}</Badge>
)

/** Red failure banner with the backend-provided reason. */
export const FailureBanner = ({ reason }: { reason: string | null }) => (
  <div role="alert" className="flex items-start gap-2 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600 ring-1 ring-red-500/30 dark:text-red-400">
    <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
    <span className="min-w-0 break-words">{reason || 'Render failed (no reason reported).'}</span>
  </div>
)
