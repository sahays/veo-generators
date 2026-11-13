import { useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { useTimelineKit } from '@/hooks/timeline/timelineContext'
import { useClockValue } from '@/hooks/timeline/useMediaClock'
import { cn } from '@/lib/utils'
import type { TimelineCue, TimelineEmotion, TimelineEntity } from '@/types/insights'
import { categoryLabel, emotionColor } from '@/types/timeline/glyphs'
import { snapshotAt, type MomentSnapshot, type TimelineModel } from '@/types/timeline/model'
import { formatTimecode } from '@/types/timeline/timeFormat'

const snapshotKey = (snapshot: MomentSnapshot): string => snapshot.key

function EmotionChip({ emotion }: { emotion: TimelineEmotion | null }): JSX.Element | null {
  if (!emotion) return null
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: emotionColor(emotion.emotion) }} />
      {categoryLabel(emotion.emotion)} {Math.round(emotion.intensity * 100)}%
    </span>
  )
}

function EntityChips({ entities, limit }: { entities: readonly TimelineEntity[]; limit: number }): JSX.Element {
  if (entities.length === 0) return <span className="text-[11px] text-muted-foreground">No one on screen</span>
  return (
    <span className="flex flex-wrap gap-1">
      {entities.slice(0, limit).map((entity) => (
        <Badge key={entity.id} variant={entity.kind === 'character' ? 'accent' : 'default'}>
          {entity.name}
        </Badge>
      ))}
      {entities.length > limit && <Badge variant="outline">+{entities.length - limit}</Badge>}
    </span>
  )
}

function CueLine({ cue, className }: { cue: TimelineCue | null; className?: string }): JSX.Element {
  if (!cue) return <p className={cn('text-muted-foreground/70', className)}>No dialogue or sound cue</p>
  const spoken = cue.kind === 'dialogue' || cue.kind === 'narration'
  return (
    <p className={cn('text-foreground', !spoken && 'italic text-muted-foreground', className)}>
      {cue.speaker && <span className="font-semibold text-accent-dark">{cue.speaker}: </span>}
      {spoken ? cue.text : `[${cue.text}]`}
    </p>
  )
}

export interface MomentHoverCardProps {
  model: TimelineModel
  timeSec: number
}

/** Hover-card body: time, segment, who is on screen, the cue and the emotion at `timeSec`. */
export function MomentHoverCard({ model, timeSec }: MomentHoverCardProps): JSX.Element {
  const snapshot = snapshotAt(model, timeSec)
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[11px] font-semibold text-accent-dark">{formatTimecode(timeSec, { tenths: true })}</span>
        <EmotionChip emotion={snapshot.emotion} />
      </div>
      <p className="font-semibold leading-snug text-foreground">{snapshot.segment?.title ?? 'No segment'}</p>
      <EntityChips entities={snapshot.entities} limit={5} />
      <CueLine cue={snapshot.cue} className="line-clamp-3 leading-snug" />
    </div>
  )
}

export interface NowStripProps {
  model: TimelineModel
  className?: string
}

/**
 * What is happening at the playhead: segment, on-screen entities, current cue
 * and emotion. It subscribes to the clock through an index lookup and
 * re-renders only when one of those actually changes, not on every frame.
 */
export function NowStrip({ model, className }: NowStripProps): JSX.Element {
  const { clock } = useTimelineKit()
  const compute = useCallback((timeSec: number) => snapshotAt(model, timeSec), [model])
  const snapshot = useClockValue(clock, compute, snapshotKey)
  return (
    <section aria-label="Now playing" aria-live="off" data-testid="now-strip" className={cn('space-y-1.5 rounded-lg border border-border bg-card px-3 py-2.5 text-xs', className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate font-semibold text-foreground">
          <span className="mr-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Now</span>
          {snapshot.segment?.title ?? 'No segment'}
        </p>
        <EmotionChip emotion={snapshot.emotion} />
      </div>
      <EntityChips entities={snapshot.entities} limit={8} />
      <CueLine cue={snapshot.cue} className="min-h-[2.5em] leading-snug" />
    </section>
  )
}
