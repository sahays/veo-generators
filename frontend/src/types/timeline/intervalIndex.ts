import type { TimeRange } from '@/types/insights'
import { lowerBound, upperBound } from './bisect'

/**
 * Immutable index over time ranges: items sorted by start, plus a running
 * maximum of end times. Both arrays are ascending, so "what is active at t"
 * and "what overlaps [a, b)" are two binary searches followed by a walk over
 * the candidate window only. For lanes whose items do not nest (segments,
 * cues, emotions, one entity's appearances) the walk touches just the hits.
 *
 * Ranges are half-open: an item is active for `start_sec <= t < end_sec`.
 */
export class IntervalIndex<T extends TimeRange> {
  readonly items: readonly T[]
  private readonly starts: Float64Array
  private readonly maxEnds: Float64Array

  constructor(items: readonly T[]) {
    this.items = [...items].sort((a, b) => a.start_sec - b.start_sec || a.end_sec - b.end_sec)
    this.starts = new Float64Array(this.items.length)
    this.maxEnds = new Float64Array(this.items.length)
    let running = -Infinity
    this.items.forEach((item, i) => {
      running = Math.max(running, item.end_sec)
      this.starts[i] = item.start_sec
      this.maxEnds[i] = running
    })
  }

  get size(): number {
    return this.items.length
  }

  /** Items intersecting the half-open window `[a, b)`, in start order. */
  overlapping(a: number, b: number): T[] {
    const hi = lowerBound(this.starts, b)
    const out: T[] = []
    for (let i = upperBound(this.maxEnds, a); i < hi; i++) {
      if (this.items[i].end_sec > a) out.push(this.items[i])
    }
    return out
  }

  /** Every item active at `t`, in start order. */
  at(t: number): T[] {
    const hi = upperBound(this.starts, t)
    const out: T[] = []
    for (let i = upperBound(this.maxEnds, t); i < hi; i++) {
      if (this.items[i].end_sec > t) out.push(this.items[i])
    }
    return out
  }

  /** The most recently started item active at `t`, or null. */
  firstAt(t: number): T | null {
    const lo = upperBound(this.maxEnds, t)
    for (let i = upperBound(this.starts, t) - 1; i >= lo; i--) {
      if (this.items[i].end_sec > t) return this.items[i]
    }
    return null
  }

  /** First item starting strictly after `t`, or null. */
  next(t: number): T | null {
    return this.items[upperBound(this.starts, t)] ?? null
  }

  /** Last item starting strictly before `t`, or null. */
  previous(t: number): T | null {
    return this.items[lowerBound(this.starts, t) - 1] ?? null
  }
}

/** Index over instantaneous markers (key moments, extrema) sorted by time. */
export class PointIndex<T extends { start_sec: number }> {
  readonly items: readonly T[]
  private readonly times: Float64Array

  constructor(items: readonly T[]) {
    this.items = [...items].sort((a, b) => a.start_sec - b.start_sec)
    this.times = Float64Array.from(this.items, (item) => item.start_sec)
  }

  get size(): number {
    return this.items.length
  }

  /** Markers with `a <= start_sec < b`. */
  between(a: number, b: number): T[] {
    return this.items.slice(lowerBound(this.times, a), lowerBound(this.times, b))
  }

  /** Latest marker at or before `t`, or null. */
  lastAtOrBefore(t: number): T | null {
    return this.items[upperBound(this.times, t) - 1] ?? null
  }
}
