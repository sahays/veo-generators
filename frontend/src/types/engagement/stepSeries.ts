import type { SignalPoint } from '@/types/insights'
import { upperBound } from '@/types/timeline/bisect'

/** Area under the signal and the seconds it covers inside some window. */
export interface SeriesSlice {
  area: number
  cover: number
}

const END_TOLERANCE_SEC = 1e-9

/**
 * An engagement signal as the report defines it: piecewise constant, the
 * value at `t` holds for `[t, t + interval)` and is cut short when the next
 * sample starts sooner. Prefix sums of area and covered time make "the value
 * at t" and "the average over [a, b)" binary searches instead of scans.
 *
 * Mirrors `SeriesIntegral` in `api/engagement_signals/engagement_series.py`,
 * so averages computed here agree with the figures in the report.
 */
export class StepSeries {
  readonly points: readonly SignalPoint[]
  readonly interval: number
  private readonly times: Float64Array
  private readonly lengths: Float64Array
  private readonly area: Float64Array
  private readonly cover: Float64Array

  constructor(points: readonly SignalPoint[], intervalSec: number) {
    const count = points.length
    this.points = points
    this.interval = intervalSec > 0 ? intervalSec : 1
    this.times = Float64Array.from(points, (point) => point[0])
    this.lengths = new Float64Array(count)
    this.area = new Float64Array(count + 1)
    this.cover = new Float64Array(count + 1)
    for (let i = 0; i < count; i++) {
      const gap = i + 1 < count ? this.times[i + 1] - this.times[i] : this.interval
      this.lengths[i] = Math.max(0, Math.min(this.interval, gap))
      this.area[i + 1] = this.area[i] + points[i][1] * this.lengths[i]
      this.cover[i + 1] = this.cover[i] + this.lengths[i]
    }
  }

  get size(): number {
    return this.points.length
  }

  /** Seconds for which the series defines a value. */
  get totalCover(): number {
    return this.cover[this.size]
  }

  /** Time-weighted mean of the whole series (0 when empty). */
  get overallMean(): number {
    return this.totalCover > 0 ? this.area[this.size] / this.totalCover : 0
  }

  /** Time at which the last sample stops holding (0 when empty). */
  get end(): number {
    const last = this.size - 1
    return last < 0 ? 0 : this.times[last] + this.lengths[last]
  }

  /**
   * Index of the sample whose value holds at `t`, or -1 when `t` is before
   * the first sample, inside a gap or after the end. The final instant of the
   * series resolves to the last sample rather than to nothing.
   */
  indexAt(t: number): number {
    const index = upperBound(this.times, t) - 1
    if (index < 0) return -1
    const into = t - this.times[index]
    if (into < this.lengths[index]) return index
    return index === this.size - 1 && into <= this.lengths[index] + END_TOLERANCE_SEC ? index : -1
  }

  valueAt(t: number): number | null {
    const index = this.indexAt(t)
    return index < 0 ? null : this.points[index][1]
  }

  /** Area and covered seconds accumulated over `(-inf, x)`. */
  private cumulative(x: number): SeriesSlice {
    const index = upperBound(this.times, x) - 1
    if (index < 0) return { area: 0, cover: 0 }
    const part = Math.min(x - this.times[index], this.lengths[index])
    return { area: this.area[index] + this.points[index][1] * part, cover: this.cover[index] + part }
  }

  /** Area and covered seconds of the series inside `[start, end)`. */
  over(startSec: number, endSec: number): SeriesSlice {
    if (!(endSec > startSec)) return { area: 0, cover: 0 }
    const hi = this.cumulative(endSec)
    const lo = this.cumulative(startSec)
    return { area: hi.area - lo.area, cover: hi.cover - lo.cover }
  }

  /** Time-weighted mean inside `[start, end)`, or null where the series has no coverage. */
  mean(startSec: number, endSec: number): number | null {
    const slice = this.over(startSec, endSec)
    return slice.cover > 0 ? slice.area / slice.cover : null
  }
}

/** Percentage difference from `baseline`; 0 when the baseline is zero. Same rule as the report. */
export function percentDelta(value: number, baseline: number): number {
  if (Math.abs(baseline) < 1e-12) return 0
  return Math.round(((value - baseline) / Math.abs(baseline)) * 10000) / 100
}
