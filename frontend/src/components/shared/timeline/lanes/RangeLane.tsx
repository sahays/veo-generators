import { useMemo } from 'react'
import { useSelectItem, useTimeScale, useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimeRange, TimelineBeat, TimelineEmotion } from '@/types/insights'
import { categoryLabel, emotionColor, glyphFor } from '@/types/timeline/glyphs'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import type { TimelineItemKind } from '@/types/timeline/model'
import { fitLabel } from '@/types/timeline/shortcuts'
import { stackRanges, type StackedSpan } from '@/types/timeline/stacking'
import { LANE_HEIGHT } from '../layout'
import { LaneItem, LaneSvg, TimelineLane } from '../TimelineLane'
import { spanBox, spokenRange } from './laneGeometry'

export interface RangeStyle {
  /** Short text drawn inside the bar when it fits. */
  text: string
  /** Spoken description, without the time range. */
  description: string
  color: string
  /** Fill opacity 0..1, e.g. an intensity. */
  opacity: number
}

interface RangeItem extends TimeRange {
  id: string
}

interface RangeBarProps<T extends RangeItem> {
  span: StackedSpan<T>
  kind: TimelineItemKind
  rowHeight: number
  tabStop: boolean
  describe: (item: T) => RangeStyle
}

function RangeBar<T extends RangeItem>({ span, kind, rowHeight, tabStop, describe }: RangeBarProps<T>): JSX.Element {
  const scale = useTimeScale()
  const select = useSelectItem()
  const item = span.items[0]
  const selected = useWorkspace((state) => state.selection?.id === item.id)
  const style = describe(item)
  const extra = span.items.length - 1
  const box = spanBox(scale, span)
  const text = fitLabel(extra > 0 ? `${style.text} +${extra}` : style.text, box.visibleWidth - 10)
  const label = `${style.description}${extra > 0 ? ` and ${extra} more` : ''}, ${spokenRange(span)}`
  const activate = (): void => select({ kind, id: item.id, label: style.description, range: item })
  return (
    <LaneItem label={label} selected={selected} tabStop={tabStop} onActivate={activate}>
      <rect className="tl-shape" x={box.x + 0.5} y={span.row * rowHeight + 2} width={Math.max(box.width - 1, 1)} height={rowHeight - 3} rx={2.5} fill={style.color} fillOpacity={style.opacity} />
      {text && (
        <text x={box.visibleX + 5} y={span.row * rowHeight + rowHeight / 2 + 3.5} fontSize={10} className="pointer-events-none fill-foreground">
          {text}
        </text>
      )}
    </LaneItem>
  )
}

export interface RangeLaneProps<T extends RangeItem> {
  id: string
  label: string
  /** Kind recorded on the selection when an item is clicked. */
  kind: TimelineItemKind
  index: IntervalIndex<T>
  describe: (item: T) => RangeStyle
  /** Rows available for ranges that overlap in time; further overlaps fold into "+N". */
  rows?: number
  height?: number
}

function RangePlot<T extends RangeItem>({ label, kind, index, describe, rows = 1, height = LANE_HEIGHT.beats }: RangeLaneProps<T>): JSX.Element {
  const scale = useTimeScale()
  const stacked = useMemo(() => stackRanges(index.items, rows), [index, rows])
  const visible = stacked.overlapping(scale.view.start, scale.view.end)
  return (
    <LaneSvg label={label} height={height}>
      {visible.map((span, i) => (
        <RangeBar key={span.items[0].id} span={span} kind={kind} rowHeight={height / rows} tabStop={i === 0} describe={describe} />
      ))}
    </LaneSvg>
  )
}

/**
 * Lane of labelled time ranges that may overlap (they stack into rows).
 * `EmotionsLane` and `BeatsLane` are presets; use this directly for other
 * range collections (events, influence ranges, ...).
 */
export function RangeLane<T extends RangeItem>(props: RangeLaneProps<T>): JSX.Element {
  return (
    <TimelineLane id={props.id} label={props.label} height={props.height ?? LANE_HEIGHT.beats}>
      <RangePlot {...props} />
    </TimelineLane>
  )
}

/** Opacity for an intensity in 0..1: weak spans stay visible, strong ones are clearly stronger. */
export function intensityOpacity(intensity: number): number {
  return 0.2 + 0.75 * Math.min(Math.max(intensity, 0), 1)
}

function describeEmotion(emotion: TimelineEmotion): RangeStyle {
  const name = categoryLabel(emotion.emotion)
  const percent = Math.round(Math.min(Math.max(emotion.intensity, 0), 1) * 100)
  return {
    text: name,
    description: `Emotion: ${name}, intensity ${percent}%`,
    color: emotionColor(emotion.emotion),
    opacity: intensityOpacity(emotion.intensity),
  }
}

function describeBeat(beat: TimelineBeat): RangeStyle {
  const name = categoryLabel(beat.beat)
  return {
    text: name,
    description: `Beat: ${name}${beat.label ? `, ${beat.label}` : ''}`,
    color: glyphFor(beat.beat).color,
    opacity: 0.32,
  }
}

interface PresetLaneProps<T extends RangeItem> {
  index: IntervalIndex<T>
  id?: string
  label?: string
}

/** Emotions over time: colour per emotion, opacity from each span's own intensity. */
export function EmotionsLane({ index, id = 'emotions', label = 'Emotions' }: PresetLaneProps<TimelineEmotion>): JSX.Element {
  return <RangeLane id={id} label={label} kind="emotion" index={index} describe={describeEmotion} rows={2} height={LANE_HEIGHT.emotions} />
}

/** Narrative beats (setup, climax, ...). */
export function BeatsLane({ index, id = 'beats', label = 'Beats' }: PresetLaneProps<TimelineBeat>): JSX.Element {
  return <RangeLane id={id} label={label} kind="beat" index={index} describe={describeBeat} />
}
