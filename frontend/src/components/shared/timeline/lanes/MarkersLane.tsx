import { useMemo } from 'react'
import { useSelectItem, useTimeScale, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimelineKeyMoment } from '@/types/insights'
import { categoryLabel, glyphFor, glyphPath, type Glyph } from '@/types/timeline/glyphs'
import type { PointIndex } from '@/types/timeline/intervalIndex'
import type { TimelineItemKind } from '@/types/timeline/model'
import { stackPoints, type StackedSpan } from '@/types/timeline/stacking'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { LANE_HEIGHT } from '../layout'
import { LaneItem, LaneSvg, TimelineLane } from '../TimelineLane'

const GLYPH_PX = 14
const GAP_PX = 3

interface PointItem {
  id: string
  start_sec: number
}

export interface MarkerStyle {
  glyph: Glyph
  /** Spoken description, without the time. */
  description: string
}

interface MarkerProps<T extends PointItem> {
  span: StackedSpan<T>
  kind: TimelineItemKind
  rowHeight: number
  tabStop: boolean
  describe: (item: T) => MarkerStyle
}

function GlyphShapePath({ glyph }: { glyph: Glyph }): JSX.Element {
  return <path className="tl-shape" d={glyphPath(glyph.shape, GLYPH_PX / 2 - 1)} fill={glyph.color} stroke="var(--card)" strokeWidth={1} />
}

/** Neutral count badge the size of a glyph, so a folded group never overlaps its neighbours. */
function ClusterBadge({ count }: { count: number }): JSX.Element {
  return (
    <>
      <circle className="tl-shape" r={GLYPH_PX / 2} fill="var(--muted-foreground)" />
      <text y={3.2} textAnchor="middle" fontSize={9} fontWeight={700} fill="var(--card)" className="pointer-events-none font-mono">
        {count > 9 ? '9+' : count}
      </text>
    </>
  )
}

/** One glyph, or a count badge when several markers were folded together (click zooms into them). */
function Marker<T extends PointItem>({ span, kind, rowHeight, tabStop, describe }: MarkerProps<T>): JSX.Element {
  const scale = useTimeScale()
  const { viewport } = useTimelineKit()
  const select = useSelectItem()
  const item = span.items[0]
  const last = span.items[span.items.length - 1]
  const selected = useWorkspace((state) => state.selection?.id === item.id)
  const style = describe(item)
  const folded = span.items.length > 1
  const label = folded
    ? `${span.items.length} markers from ${formatTimecode(item.start_sec)}. Activate to zoom in`
    : `${style.description}, at ${formatTimecode(item.start_sec)}`
  const activate = (): void => {
    if (folded) return viewport.showRange({ start_sec: item.start_sec, end_sec: last.start_sec }, 1)
    select({ kind, id: item.id, label: style.description, range: { start_sec: item.start_sec, end_sec: item.start_sec } })
  }
  return (
    <LaneItem label={label} selected={selected} tabStop={tabStop} onActivate={activate}>
      <g transform={`translate(${scale.toX(item.start_sec)},${span.row * rowHeight + rowHeight / 2})`}>
        {folded ? <ClusterBadge count={span.items.length} /> : <GlyphShapePath glyph={style.glyph} />}
      </g>
    </LaneItem>
  )
}

export interface MarkersLaneProps<T extends PointItem> {
  id: string
  label: string
  /** Kind recorded on the selection when a marker is clicked. */
  kind: TimelineItemKind
  points: PointIndex<T>
  describe: (item: T) => MarkerStyle
  rows?: number
  height?: number
}

function MarkersPlot<T extends PointItem>({ label, kind, points, describe, rows = 3, height = LANE_HEIGHT.markers }: MarkersLaneProps<T>): JSX.Element {
  const scale = useTimeScale()
  const stacked = useMemo(
    () => stackPoints(points.items, scale.pxPerSec, GLYPH_PX, { gap: GAP_PX, maxRows: rows }),
    [points, scale.pxPerSec, rows],
  )
  const visible = stacked.overlapping(scale.view.start, scale.view.end)
  return (
    <LaneSvg label={label} height={height}>
      {visible.map((span, i) => (
        <Marker key={span.items[0].id} span={span} kind={kind} rowHeight={height / rows} tabStop={i === 0} describe={describe} />
      ))}
    </LaneSvg>
  )
}

/**
 * Lane of point markers. Each marker is a glyph whose shape and colour come
 * from `describe`; glyphs that would collide are stacked into rows, and
 * folded into a count badge when the rows run out, so they never overlap.
 * `KeyMomentsLane` is a preset; use this directly for other point data
 * (peaks, valleys, drop-offs).
 */
export function MarkersLane<T extends PointItem>(props: MarkersLaneProps<T>): JSX.Element {
  return (
    <TimelineLane id={props.id} label={props.label} height={props.height ?? LANE_HEIGHT.markers}>
      <MarkersPlot {...props} />
    </TimelineLane>
  )
}

function describeMoment(moment: TimelineKeyMoment): MarkerStyle {
  return { glyph: glyphFor(moment.type), description: `${categoryLabel(moment.type)}: ${moment.label}` }
}

export interface KeyMomentsLaneProps {
  points: PointIndex<TimelineKeyMoment>
  id?: string
  label?: string
}

/** Key moments, one glyph shape and colour per moment type. */
export function KeyMomentsLane({ points, id = 'moments', label = 'Key moments' }: KeyMomentsLaneProps): JSX.Element {
  return <MarkersLane id={id} label={label} kind="moment" points={points} describe={describeMoment} />
}
