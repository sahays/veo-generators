import { useMemo } from 'react'
import {
  BeatsLane,
  DensityLane,
  EmotionsLane,
  ENTITY_LANES_ID,
  EntityLanes,
  FilmstripLane,
  KeyMomentsLane,
  Minimap,
  MomentHoverCard,
  RulerLane,
  SegmentsLane,
  TimelineSurface,
  TimelineToolbar,
  type LaneOption,
} from '@/components/shared/timeline'
import type { FilmstripInfo } from '@/types/insights'
import { IntervalIndex } from '@/types/timeline/intervalIndex'
import type { TimelineModel } from '@/types/timeline/model'

const LANE_OPTIONS: LaneOption[] = [
  { id: 'filmstrip', label: 'Filmstrip' },
  { id: 'segments', label: 'Segments' },
  { id: 'moments', label: 'Key moments' },
  { id: 'beats', label: 'Narrative beats' },
  { id: 'emotions', label: 'Emotions' },
  { id: ENTITY_LANES_ID, label: 'Pinned entities' },
  { id: 'density', label: 'Speech density' },
]

export interface SceneTimelineProps {
  model: TimelineModel
  filmstrip: FilmstripInfo | null
}

/** The Scene Analysis timeline: toolbar, lanes on one shared scale, and the minimap. */
export function SceneTimeline({ model, filmstrip }: SceneTimelineProps): JSX.Element {
  const speech = useMemo(
    () => new IntervalIndex(model.doc.cues.filter((cue) => cue.kind === 'dialogue' || cue.kind === 'narration')),
    [model],
  )
  const lanes = filmstrip ? LANE_OPTIONS : LANE_OPTIONS.filter((lane) => lane.id !== 'filmstrip')
  return (
    <section aria-label="Timeline" className="space-y-2">
      <TimelineToolbar lanes={lanes} />
      <TimelineSurface ariaLabel="Scene timeline" hoverCard={(timeSec) => <MomentHoverCard model={model} timeSec={timeSec} />}>
        <RulerLane />
        <FilmstripLane filmstrip={filmstrip} />
        <SegmentsLane segments={model.segments} />
        <KeyMomentsLane points={model.moments} />
        <BeatsLane index={model.beats} />
        <EmotionsLane index={model.emotions} />
        <EntityLanes entityById={model.entityById} entityRanges={model.entityRanges} emptyHint="Pin entities in the Entities tab to compare them here." />
        <DensityLane index={speech} label="Speech density" />
      </TimelineSurface>
      <Minimap ranges={model.doc.segments} />
      <p className="text-[11px] text-muted-foreground">
        Scroll to zoom at the cursor, drag to pan, click the ruler to scrub, Shift-drag the ruler to select a range. Timestamps come from the model and are approximate.
      </p>
    </section>
  )
}
