import { useTimelineKit } from '@/hooks/timeline/timelineContext'
import { usePlayerShortcuts } from '@/hooks/timeline/usePlayerShortcuts'
import { cn } from '@/lib/utils'
import type { TimeRange } from '@/types/insights'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { PlayerControls } from './PlayerControls'

export interface SyncedVideoPlayerProps {
  /** Video URL (the record's `video_signed_url`). */
  src: string | undefined
  /** Segments for the `[` / `]` shortcuts and the skip buttons. */
  segments?: IntervalIndex<TimeRange> | null
  /** Accessible name of the video. */
  title?: string
  className?: string
  /** Rendered under the controls, e.g. `<NowStrip>`. */
  children?: React.ReactNode
}

/**
 * The video bound to the workspace clock. Everything else in the workspace
 * (playhead, panels, charts) follows this element through the clock.
 *
 * Keyboard: Space or K play/pause, Left/Right 5 s, J/L 10 s, `[` / `]`
 * previous/next segment. Seeking, from here or from anywhere else, never
 * pauses playback and never scrolls the page.
 */
export function SyncedVideoPlayer({ src, segments = null, title = 'Video', className, children }: SyncedVideoPlayerProps): JSX.Element {
  const { clock } = useTimelineKit()
  usePlayerShortcuts(segments)
  return (
    <div className={cn('space-y-2', className)}>
      <div className="overflow-hidden rounded-lg border border-border bg-black">
        <video
          ref={clock.attach}
          src={src}
          aria-label={title}
          data-testid="player-video"
          playsInline
          preload="auto"
          className="aspect-video w-full cursor-pointer object-contain"
          onClick={() => clock.toggle()}
        />
      </div>
      <PlayerControls segments={segments} />
      {children}
    </div>
  )
}
