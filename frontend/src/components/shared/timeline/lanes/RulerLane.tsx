import { useMemo } from 'react'
import { useSeek, useTimeScale, useTimelineKit } from '@/hooks/timeline/timelineContext'
import { useClockTime } from '@/hooks/timeline/useMediaClock'
import { NO_PAN_ATTR } from '@/hooks/timeline/useTimelineGestures'
import { useTimeScrub } from '@/hooks/timeline/useTimeScrub'
import { buildTicks } from '@/types/timeline/ticks'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { LANE_HEIGHT } from '../layout'
import { TimelineLane } from '../TimelineLane'

const KEY_STEP_SEC = 1
const KEY_BIG_STEP_SEC = 5

function RulerTicks({ height }: { height: number }): JSX.Element {
  const scale = useTimeScale()
  const ticks = useMemo(() => buildTicks(scale.view, scale.width), [scale])
  const tenths = ticks.step < 1
  return (
    <svg aria-hidden width={scale.width} height={height} className="block text-muted-foreground">
      {ticks.minor.map((t) => (
        <line key={`m${t}`} x1={scale.toX(t)} x2={scale.toX(t)} y1={height - 5} y2={height} stroke="currentColor" opacity={0.35} />
      ))}
      {ticks.major.map((t) => (
        <g key={t} transform={`translate(${scale.toX(t)},0)`}>
          <line y1={height - 10} y2={height} stroke="currentColor" opacity={0.7} />
          <text x={4} y={12} fontSize={10} fill="currentColor" className="font-mono">
            {formatTimecode(t, { tenths })}
          </text>
        </g>
      ))}
    </svg>
  )
}

/** Keyboard seeking on the focused ruler: arrows 1 s (Shift 5 s), Home, End. */
function useRulerKeys(): (event: React.KeyboardEvent<HTMLDivElement>) => void {
  const { clock, duration } = useTimelineKit()
  const seek = useSeek()
  return (event) => {
    const step = event.shiftKey ? KEY_BIG_STEP_SEC : KEY_STEP_SEC
    const targets: Record<string, number> = {
      ArrowLeft: clock.getTime() - step,
      ArrowRight: clock.getTime() + step,
      Home: 0,
      End: duration,
    }
    const target = targets[event.key]
    if (target === undefined) return
    event.preventDefault()
    seek(target)
  }
}

/** Transparent slider laid over the ticks: the scrub target for pointer and keyboard. */
function RulerScrubber(): JSX.Element {
  const { clock, duration } = useTimelineKit()
  const now = useClockTime(clock, 1)
  const scrub = useTimeScrub()
  const onKeyDown = useRulerKeys()
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label="Playhead position. Drag to scrub, Shift and drag to select a range"
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(now)}
      aria-valuetext={formatTimecode(now)}
      data-testid="timeline-ruler"
      {...{ [NO_PAN_ATTR]: '' }}
      className="tl-focusable absolute inset-0 cursor-col-resize touch-none"
      onKeyDown={onKeyDown}
      {...scrub}
    />
  )
}

/** Time ruler. Click or drag to scrub; Shift+drag selects a range; arrow keys seek when focused. */
export function RulerLane({ label = 'Time' }: { label?: string }): JSX.Element {
  return (
    <TimelineLane id="ruler" label={label} height={LANE_HEIGHT.ruler} className="bg-muted/20">
      <RulerTicks height={LANE_HEIGHT.ruler} />
      <RulerScrubber />
    </TimelineLane>
  )
}
