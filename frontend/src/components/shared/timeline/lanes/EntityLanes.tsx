import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useSelectItem, useTimeScale, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimeRange, TimelineEntity } from '@/types/insights'
import { chartColor } from '@/types/timeline/glyphs'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { LANE_HEIGHT } from '../layout'
import { LaneItem, LaneSvg, TimelineLane } from '../TimelineLane'
import { spanBox, spokenRange } from './laneGeometry'

const HEIGHT = LANE_HEIGHT.entity

/** Lane-visibility id that shows or hides all pinned-entity lanes together. */
export const ENTITY_LANES_ID = 'entities'

interface AppearanceBarProps {
  entity: TimelineEntity
  range: TimeRange
  color: string
  tabStop: boolean
}

function AppearanceBar({ entity, range, color, tabStop }: AppearanceBarProps): JSX.Element {
  const scale = useTimeScale()
  const select = useSelectItem()
  const box = spanBox(scale, range)
  const activate = (): void => select({ kind: 'entity', id: entity.id, label: entity.name, range })
  return (
    <LaneItem label={`${entity.name} on screen, ${spokenRange(range)}`} tabStop={tabStop} onActivate={activate}>
      <rect className="tl-shape" x={box.x} y={5} width={box.width} height={HEIGHT - 10} rx={3} fill={color} fillOpacity={0.85} />
    </LaneItem>
  )
}

interface EntityLaneProps {
  entity: TimelineEntity
  ranges: IntervalIndex<TimeRange>
  color: string
}

function EntityLane({ entity, ranges, color }: EntityLaneProps): JSX.Element {
  const scale = useTimeScale()
  const { store } = useTimelineKit()
  const visible = ranges.overlapping(scale.view.start, scale.view.end)
  const unpin = (
    <Button variant="ghost" size="none" className="h-5 w-5 shrink-0 rounded" aria-label={`Unpin ${entity.name}`} onClick={() => store.getState().togglePin(entity.id)}>
      <X size={11} />
    </Button>
  )
  return (
    <TimelineLane id={`entity:${entity.id}`} label={entity.name} labelExtra={unpin} height={HEIGHT}>
      <LaneSvg label={`${entity.name} appearances`} height={HEIGHT}>
        {visible.map((range, i) => (
          <AppearanceBar key={range.start_sec} entity={entity} range={range} color={color} tabStop={i === 0} />
        ))}
      </LaneSvg>
    </TimelineLane>
  )
}

export interface EntityLanesProps {
  entityById: ReadonlyMap<string, TimelineEntity>
  entityRanges: ReadonlyMap<string, IntervalIndex<TimeRange>>
  /** Shown in place of the lanes while nothing is pinned. */
  emptyHint?: string
}

/**
 * One appearance lane per pinned entity (pins live in the workspace store, so
 * the entity browser and these lanes stay in step). Each bar is one on-screen
 * range; clicking it seeks to that appearance.
 */
export function EntityLanes({ entityById, entityRanges, emptyHint }: EntityLanesProps): JSX.Element | null {
  const pinned = useWorkspace((state) => state.pinnedEntityIds)
  const hidden = useWorkspace((state) => state.hiddenLanes.includes(ENTITY_LANES_ID))
  if (hidden) return null
  if (pinned.length === 0) {
    if (!emptyHint) return null
    return (
      <TimelineLane id={ENTITY_LANES_ID} label="Entities" height={HEIGHT}>
        <p className="flex h-full cursor-default items-center px-2 text-[10.5px] text-muted-foreground">{emptyHint}</p>
      </TimelineLane>
    )
  }
  return (
    <>
      {pinned.map((id, i) => {
        const entity = entityById.get(id)
        const ranges = entityRanges.get(id)
        return entity && ranges ? <EntityLane key={id} entity={entity} ranges={ranges} color={chartColor(i)} /> : null
      })}
    </>
  )
}
