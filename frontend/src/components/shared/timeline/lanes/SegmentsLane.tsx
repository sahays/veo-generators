import { useMemo } from 'react'
import { useSelectItem, useTimeScale, useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimelineSegment } from '@/types/insights'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { fitLabel } from '@/types/timeline/shortcuts'
import { LANE_HEIGHT } from '../layout'
import { LaneItem, LaneSvg, TimelineLane } from '../TimelineLane'
import { spanBox, spokenRange } from './laneGeometry'

const HEIGHT = LANE_HEIGHT.segments
const LABEL_PAD_PX = 6

interface SegmentBlockProps {
  segment: TimelineSegment
  ordinal: number
  tabStop: boolean
}

function SegmentBlock({ segment, ordinal, tabStop }: SegmentBlockProps): JSX.Element {
  const scale = useTimeScale()
  const select = useSelectItem()
  const selected = useWorkspace((state) => state.selection?.id === segment.id)
  const box = spanBox(scale, segment)
  const text = fitLabel(segment.title, box.visibleWidth - LABEL_PAD_PX * 2)
  const activate = (): void => select({ kind: 'segment', id: segment.id, label: segment.title, range: segment })
  return (
    <LaneItem label={`Segment ${ordinal + 1}: ${segment.title}, ${spokenRange(segment)}`} selected={selected} tabStop={tabStop} onActivate={activate}>
      <rect
        className="tl-shape"
        x={box.x + 0.5}
        y={3}
        width={Math.max(box.width - 1, 1)}
        height={HEIGHT - 6}
        rx={3}
        fill={ordinal % 2 === 0 ? 'var(--chart-2)' : 'var(--chart-7)'}
        fillOpacity={selected ? 0.5 : 0.28}
      />
      {text && (
        <text x={box.visibleX + LABEL_PAD_PX} y={HEIGHT / 2 + 3.5} fontSize={10.5} className="pointer-events-none fill-foreground">
          {text}
        </text>
      )}
    </LaneItem>
  )
}

function SegmentsPlot({ segments, label }: { segments: IntervalIndex<TimelineSegment>; label: string }): JSX.Element {
  const scale = useTimeScale()
  const ordinals = useMemo(() => new Map(segments.items.map((segment, i) => [segment.id, i])), [segments])
  const visible = segments.overlapping(scale.view.start, scale.view.end)
  return (
    <LaneSvg label={label} height={HEIGHT}>
      {visible.map((segment, i) => (
        <SegmentBlock key={segment.id} segment={segment} ordinal={ordinals.get(segment.id) ?? 0} tabStop={i === 0} />
      ))}
    </LaneSvg>
  )
}

export interface SegmentsLaneProps {
  segments: IntervalIndex<TimelineSegment>
  id?: string
  label?: string
}

/** Scene segments as contiguous blocks. Click selects the segment and seeks to its start. */
export function SegmentsLane({ segments, id = 'segments', label = 'Segments' }: SegmentsLaneProps): JSX.Element {
  return (
    <TimelineLane id={id} label={label} height={HEIGHT}>
      <SegmentsPlot segments={segments} label={label} />
    </TimelineLane>
  )
}
