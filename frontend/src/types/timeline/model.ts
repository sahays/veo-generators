import type {
  TimeRange,
  TimelineAdOpportunity,
  TimelineBeat,
  TimelineCue,
  TimelineDoc,
  TimelineEmotion,
  TimelineEntity,
  TimelineEvent,
  TimelineKeyMoment,
  TimelineSegment,
} from '@/types/insights'
import { IntervalIndex, PointIndex } from './intervalIndex'

/** One on-screen range of one entity, flattened for "who is on screen at t". */
export interface EntityAppearance extends TimeRange {
  entity_id: string
}

/** `extremum` is a peak, valley or drop of an engagement curve; it is not part of a `TimelineDoc`. */
export type TimelineItemKind =
  | 'segment'
  | 'cue'
  | 'entity'
  | 'event'
  | 'emotion'
  | 'moment'
  | 'beat'
  | 'ad_opportunity'
  | 'extremum'

/** Addressable timeline item: what a selection or a deep link points at. */
export interface TimelineItemRef {
  kind: TimelineItemKind
  id: string
  label: string
  /** Point items (key moments) have `end_sec === start_sec`. */
  range: TimeRange
}

/**
 * A `TimelineDoc` with every lookup structure built once. Lanes, panels, the
 * hover card and the "now" strip all read from this; none of them filters the
 * raw arrays.
 */
export interface TimelineModel {
  doc: TimelineDoc
  duration: number
  segments: IntervalIndex<TimelineSegment>
  cues: IntervalIndex<TimelineCue>
  events: IntervalIndex<TimelineEvent>
  emotions: IntervalIndex<TimelineEmotion>
  beats: IntervalIndex<TimelineBeat>
  adOpportunities: IntervalIndex<TimelineAdOpportunity>
  moments: PointIndex<TimelineKeyMoment>
  appearances: IntervalIndex<EntityAppearance>
  entityById: Map<string, TimelineEntity>
  entityRanges: Map<string, IntervalIndex<TimeRange>>
  itemsById: Map<string, TimelineItemRef>
}

/** What is happening at one instant. `key` changes only when the content does. */
export interface MomentSnapshot {
  key: string
  segment: TimelineSegment | null
  cue: TimelineCue | null
  emotion: TimelineEmotion | null
  entities: TimelineEntity[]
}

function ranged<T extends TimeRange & { id: string }>(
  kind: TimelineItemKind,
  items: readonly T[],
  label: (item: T) => string,
): TimelineItemRef[] {
  return items.map((item) => ({
    kind,
    id: item.id,
    label: label(item),
    range: { start_sec: item.start_sec, end_sec: item.end_sec },
  }))
}

function entityRef(entity: TimelineEntity): TimelineItemRef {
  const first = entity.appearances[0]
  const range = first ? { start_sec: first.start_sec, end_sec: first.end_sec } : { start_sec: 0, end_sec: 0 }
  return { kind: 'entity', id: entity.id, label: entity.name, range }
}

function momentRef(moment: TimelineKeyMoment): TimelineItemRef {
  const range = { start_sec: moment.start_sec, end_sec: moment.start_sec }
  return { kind: 'moment', id: moment.id, label: moment.label, range }
}

function collectItemRefs(doc: TimelineDoc): Map<string, TimelineItemRef> {
  const refs = [
    ...ranged('segment', doc.segments, (s) => s.title),
    ...ranged('cue', doc.cues, (c) => c.text),
    ...ranged('event', doc.events, (e) => e.description || e.tag),
    ...ranged('emotion', doc.emotions, (e) => e.emotion),
    ...ranged('beat', doc.narrative_beats, (b) => b.label || b.beat),
    ...ranged('ad_opportunity', doc.ad_opportunities ?? [], (a) => a.suggested_category),
    ...doc.entities.map(entityRef),
    ...doc.key_moments.map(momentRef),
  ]
  return new Map(refs.map((ref) => [ref.id, ref]))
}

function flattenAppearances(entities: readonly TimelineEntity[]): EntityAppearance[] {
  return entities.flatMap((entity) =>
    entity.appearances.map((a) => ({ entity_id: entity.id, start_sec: a.start_sec, end_sec: a.end_sec })),
  )
}

export function buildTimelineModel(doc: TimelineDoc): TimelineModel {
  return {
    doc,
    duration: doc.duration_sec,
    segments: new IntervalIndex(doc.segments),
    cues: new IntervalIndex(doc.cues),
    events: new IntervalIndex(doc.events),
    emotions: new IntervalIndex(doc.emotions),
    beats: new IntervalIndex(doc.narrative_beats),
    adOpportunities: new IntervalIndex(doc.ad_opportunities ?? []),
    moments: new PointIndex(doc.key_moments),
    appearances: new IntervalIndex(flattenAppearances(doc.entities)),
    entityById: new Map(doc.entities.map((e) => [e.id, e])),
    entityRanges: new Map(doc.entities.map((e) => [e.id, new IntervalIndex(e.appearances)])),
    itemsById: collectItemRefs(doc),
  }
}

function strongest(emotions: readonly TimelineEmotion[]): TimelineEmotion | null {
  return emotions.reduce<TimelineEmotion | null>((best, e) => (best && best.intensity >= e.intensity ? best : e), null)
}

/** Entities on screen at `t`, without duplicates, in document (screen-time) order. */
function entitiesAt(model: TimelineModel, t: number): TimelineEntity[] {
  const ids = new Set(model.appearances.at(t).map((a) => a.entity_id))
  const found: TimelineEntity[] = []
  ids.forEach((id) => {
    const entity = model.entityById.get(id)
    if (entity) found.push(entity)
  })
  return found.sort((a, b) => b.screen_time_sec - a.screen_time_sec)
}

/**
 * Segment, cue, strongest emotion and on-screen entities at `t`. The final
 * instant of the video resolves to the last items rather than to nothing.
 */
export function snapshotAt(model: TimelineModel, t: number): MomentSnapshot {
  const time = Math.min(Math.max(t, 0), Math.max(model.duration - 0.001, 0))
  const segment = model.segments.firstAt(time)
  const cue = model.cues.firstAt(time)
  const emotion = strongest(model.emotions.at(time))
  const entities = entitiesAt(model, time)
  const key = [segment?.id, cue?.id, emotion?.id, entities.map((e) => e.id).join('+')].join('|')
  return { key, segment, cue, emotion, entities }
}

/** Distinct speaker names in order of first appearance. */
export function listSpeakers(cues: readonly TimelineCue[]): string[] {
  const seen = new Set<string>()
  cues.forEach((cue) => {
    if (cue.speaker?.trim()) seen.add(cue.speaker.trim())
  })
  return [...seen]
}

/**
 * Entities pinned when a workspace opens: the most visible characters, or the
 * most visible entities when the video has no characters. `entities` is in
 * document order (descending screen time).
 */
export function defaultPinnedEntityIds(entities: readonly TimelineEntity[], count = 2): string[] {
  const characters = entities.filter((entity) => entity.kind === 'character')
  return (characters.length > 0 ? characters : entities).slice(0, count).map((entity) => entity.id)
}
