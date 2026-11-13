import type { TimeRange, TimelineCue, TimelineEntity, TimelineSegment } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import type { ReportModel } from './reportModel'
import { percentDelta } from './stepSeries'

export interface EntityPresence {
  entity: TimelineEntity
  /** Seconds on screen inside the range. */
  seconds: number
}

/** What happened, and how the curve behaved, inside one time range. */
export interface RangeSummary {
  range: TimeRange
  /** Time-weighted average of the primary metric inside the range; null where the signal has no samples. */
  average: number | null
  /** `average` against the overall average, in percent; null with `average`. */
  deltaPct: number | null
  /** Seconds of the range the signal covers. */
  coveredSec: number
  segments: TimelineSegment[]
  /** Entities on screen inside the range, longest presence first. */
  entities: EntityPresence[]
  cues: TimelineCue[]
}

/** Entities with their on-screen seconds inside `range`. Reads only the appearances that overlap it. */
function presenceIn(timeline: TimelineModel, range: TimeRange): EntityPresence[] {
  const seconds = new Map<string, number>()
  timeline.appearances.overlapping(range.start_sec, range.end_sec).forEach((appearance) => {
    const inside = Math.min(appearance.end_sec, range.end_sec) - Math.max(appearance.start_sec, range.start_sec)
    seconds.set(appearance.entity_id, (seconds.get(appearance.entity_id) ?? 0) + Math.max(inside, 0))
  })
  const present: EntityPresence[] = []
  seconds.forEach((value, id) => {
    const entity = timeline.entityById.get(id)
    if (entity) present.push({ entity, seconds: value })
  })
  return present.sort((a, b) => b.seconds - a.seconds)
}

/**
 * Summary of a selected range: its average against the overall average (a
 * prefix-sum lookup, not a scan of the samples), who is on screen and the
 * cues inside it.
 */
export function summariseRange(report: ReportModel, timeline: TimelineModel, range: TimeRange): RangeSummary {
  const slice = report.primary.series.over(range.start_sec, range.end_sec)
  const average = slice.cover > 0 ? slice.area / slice.cover : null
  return {
    range,
    average,
    deltaPct: average === null ? null : percentDelta(average, report.average),
    coveredSec: slice.cover,
    segments: timeline.segments.overlapping(range.start_sec, range.end_sec),
    entities: presenceIn(timeline, range),
    cues: timeline.cues.overlapping(range.start_sec, range.end_sec),
  }
}
