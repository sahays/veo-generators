import { useTimeScale } from '@/hooks/timeline/timelineContext'
import type { TimeRange } from '@/types/insights'
import { coverageBins } from '@/types/timeline/downsample'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { LANE_HEIGHT } from '../layout'
import { TimelineLane } from '../TimelineLane'

const HEIGHT = LANE_HEIGHT.density
const BIN_PX = 4

function DensityPlot({ index, label }: { index: IntervalIndex<TimeRange>; label: string }): JSX.Element {
  const scale = useTimeScale()
  const binCount = Math.floor(scale.width / BIN_PX)
  const visible = index.overlapping(scale.view.start, scale.view.end)
  const bins = coverageBins(visible, scale.view, binCount)
  return (
    <svg role="img" aria-label={`${label}: share of each moment covered`} width={scale.width} height={HEIGHT} className="block">
      {bins.map((share, i) =>
        share > 0 ? (
          <rect key={i} x={i * BIN_PX + 0.5} y={HEIGHT - 2 - share * (HEIGHT - 6)} width={BIN_PX - 1} height={share * (HEIGHT - 6)} rx={1} fill="var(--chart-1)" fillOpacity={0.35 + 0.5 * share} />
        ) : null,
      )}
      <line x1={0} x2={scale.width} y1={HEIGHT - 1.5} y2={HEIGHT - 1.5} stroke="var(--border)" />
    </svg>
  )
}

export interface DensityLaneProps {
  /** Ranges to measure, e.g. spoken cues. */
  index: IntervalIndex<TimeRange>
  id?: string
  label?: string
}

/**
 * How much of each slice of the visible range is covered by the given ranges
 * (for cues: how wall-to-wall the talking is). One bar per few pixels,
 * computed from the visible ranges only.
 */
export function DensityLane({ index, id = 'density', label = 'Cue density' }: DensityLaneProps): JSX.Element {
  return (
    <TimelineLane id={id} label={label} height={HEIGHT}>
      <DensityPlot index={index} label={label} />
    </TimelineLane>
  )
}
