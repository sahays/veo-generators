import { useEffect, useRef } from 'react'
import { Pause, Play, Repeat, SkipBack, SkipForward, Volume2, VolumeX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { useSeek, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import { useClockState, useClockTime } from '@/hooks/timeline/useMediaClock'
import { cn } from '@/lib/utils'
import type { TimeRange } from '@/types/insights'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { segmentJumpTarget } from '@/types/timeline/shortcuts'
import { formatTimecode } from '@/types/timeline/timeFormat'

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2]

function PlayButton(): JSX.Element {
  const { clock } = useTimelineKit()
  const { playing } = useClockState(clock)
  return (
    <Button variant="primary" size="icon" aria-label={playing ? 'Pause (Space)' : 'Play (Space)'} data-testid="player-play" onClick={() => clock.toggle()}>
      {playing ? <Pause size={15} /> : <Play size={15} />}
    </Button>
  )
}

/** Current time and duration. Re-renders ten times a second at most, and only this text. */
function TimeReadout(): JSX.Element {
  const { clock } = useTimelineKit()
  const { duration } = useClockState(clock)
  const now = useClockTime(clock, 0.1)
  return (
    <span data-testid="player-time" className="whitespace-nowrap font-mono text-[11px] tabular-nums text-foreground">
      {formatTimecode(now, { tenths: true })}
      <span className="text-muted-foreground"> / {formatTimecode(duration)}</span>
    </span>
  )
}

/**
 * Seek bar. Its position is written straight to the input by a clock
 * subscription; dragging it seeks without pausing.
 */
function SeekBar(): JSX.Element {
  const { clock } = useTimelineKit()
  const { duration } = useClockState(clock)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const sync = (): void => {
      const input = ref.current
      if (!input) return
      input.value = String(clock.getTime())
      input.setAttribute('aria-valuetext', formatTimecode(clock.getTime()))
    }
    sync()
    return clock.subscribeTime(sync)
  }, [clock, duration])
  return (
    <input
      ref={ref}
      type="range"
      min={0}
      max={duration || 1}
      step={0.05}
      defaultValue={0}
      aria-label="Seek"
      data-testid="player-seek"
      className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--accent)]"
      onChange={(event) => clock.seek(Number(event.target.value))}
    />
  )
}

function SegmentButtons({ segments }: { segments: IntervalIndex<TimeRange> }): JSX.Element {
  const { clock } = useTimelineKit()
  const seek = useSeek()
  const jump = (direction: -1 | 1): void => {
    const target = segmentJumpTarget(segments, clock.getTime(), direction)
    if (target !== null) seek(target)
  }
  return (
    <>
      <Button variant="ghost" size="icon" aria-label="Previous segment ([)" onClick={() => jump(-1)}>
        <SkipBack size={14} />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Next segment (])" onClick={() => jump(1)}>
        <SkipForward size={14} />
      </Button>
    </>
  )
}

function RateSelect(): JSX.Element {
  const { clock } = useTimelineKit()
  const { rate } = useClockState(clock)
  return (
    <Select
      size="sm"
      ariaLabel="Playback speed"
      dataTestId="player-rate"
      className="w-[4.25rem] shrink-0"
      value={String(rate)}
      onChange={(val) => clock.setRate(Number(val))}
      options={RATES.map((value) => ({ value: String(value), label: `${value}×` }))}
    />
  )
}

function MuteButton(): JSX.Element {
  const { clock } = useTimelineKit()
  const { muted } = useClockState(clock)
  return (
    <Button variant="ghost" size="icon" aria-label={muted ? 'Unmute' : 'Mute'} aria-pressed={muted} onClick={() => clock.setMuted(!muted)}>
      {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
    </Button>
  )
}

/** Toggle looping of the selected range. Disabled until a range with length is selected. */
function LoopButton(): JSX.Element {
  const { store } = useTimelineKit()
  const looping = useWorkspace((state) => state.loopSelection)
  const hasRange = useWorkspace((state) => Boolean(state.selection && state.selection.range.end_sec > state.selection.range.start_sec))
  const label = hasRange ? 'Loop the selected range' : 'Loop (select a segment or range first)'
  return (
    <Button
      variant={looping ? 'secondary' : 'ghost'}
      size="icon"
      aria-label={label}
      title={label}
      aria-pressed={looping}
      data-testid="player-loop"
      disabled={!hasRange && !looping}
      className={cn(looping && 'text-accent-dark')}
      onClick={() => store.getState().setLoopSelection(!looping)}
    >
      <Repeat size={14} />
    </Button>
  )
}

export interface PlayerControlsProps {
  /** Enables the previous/next segment buttons. */
  segments?: IntervalIndex<TimeRange> | null
  className?: string
}

/** Transport bar for the synced player: play, segment skip, seek, time, speed, loop, mute. */
export function PlayerControls({ segments, className }: PlayerControlsProps): JSX.Element {
  return (
    <div role="group" aria-label="Player controls" className={cn('flex items-center gap-1.5', className)}>
      <PlayButton />
      {segments && <SegmentButtons segments={segments} />}
      <SeekBar />
      <TimeReadout />
      <RateSelect />
      <LoopButton />
      <MuteButton />
    </div>
  )
}
