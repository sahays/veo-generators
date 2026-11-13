import { describe, expect, it } from 'vitest'
import type { SignalPoint } from '@/types/insights'
import { StepSeries, percentDelta } from '../stepSeries'

const TEN_SECOND_STEPS: SignalPoint[] = [[0, 10], [10, 20], [20, 30]]

/** Reference implementation: walk every sample and add up its overlap with the window. */
function naiveMean(points: readonly SignalPoint[], interval: number, start: number, end: number): number | null {
  let area = 0
  let cover = 0
  points.forEach(([time, value], i) => {
    const next = points[i + 1]
    const holdsUntil = Math.min(time + interval, next ? next[0] : Infinity)
    const overlap = Math.min(holdsUntil, end) - Math.max(time, start)
    if (overlap > 0) {
      area += value * overlap
      cover += overlap
    }
  })
  return cover > 0 ? area / cover : null
}

/** Small deterministic generator so the randomised test is repeatable. */
function seededRandom(seed: number): () => number {
  let state = seed
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296
    return state / 4294967296
  }
}

function randomSeries(random: () => number, count: number): SignalPoint[] {
  const points: SignalPoint[] = []
  let time = random() * 3
  for (let i = 0; i < count; i++) {
    points.push([Math.round(time * 100) / 100, Math.round(random() * 1000) / 10])
    // Mostly regular spacing, with the odd early sample and the odd gap.
    time += random() < 0.15 ? 0.4 : random() < 0.15 ? 5.5 : 2
  }
  return points
}

describe('StepSeries.valueAt', () => {
  const series = new StepSeries(TEN_SECOND_STEPS, 10)

  it('holds each value from its sample time until the next one', () => {
    expect(series.valueAt(0)).toBe(10)
    expect(series.valueAt(9.999)).toBe(10)
    expect(series.valueAt(10)).toBe(20)
    expect(series.valueAt(29.5)).toBe(30)
  })

  it('has no value before the first sample or after the last one stops holding', () => {
    expect(new StepSeries([[5, 1]], 10).valueAt(4.99)).toBeNull()
    expect(series.valueAt(30.01)).toBeNull()
    expect(series.end).toBe(30)
  })

  it('resolves the final instant to the last sample', () => {
    expect(series.valueAt(30)).toBe(30)
    expect(series.indexAt(30)).toBe(2)
  })

  it('has no value inside a gap longer than the interval', () => {
    const gappy = new StepSeries([[0, 10], [30, 40]], 10)
    expect(gappy.valueAt(9.9)).toBe(10)
    expect(gappy.valueAt(10)).toBeNull()
    expect(gappy.valueAt(29.9)).toBeNull()
    expect(gappy.valueAt(30)).toBe(40)
  })
})

describe('StepSeries.mean', () => {
  it('weights partial samples at both ends of the range by their overlap', () => {
    const series = new StepSeries(TEN_SECOND_STEPS, 10)
    // 5 s of 10, 10 s of 20, 5 s of 30.
    expect(series.mean(5, 25)).toBeCloseTo(20, 10)
    // 2 s of 10 and 1 s of 20.
    expect(series.mean(8, 11)).toBeCloseTo((2 * 10 + 20) / 3, 10)
    expect(series.mean(0, 30)).toBeCloseTo(series.overallMean, 10)
  })

  it('averages only over the time the signal covers', () => {
    const gappy = new StepSeries([[0, 10], [30, 40]], 10)
    expect(gappy.mean(0, 40)).toBeCloseTo(25, 10)
    expect(gappy.over(0, 40).cover).toBeCloseTo(20, 10)
    expect(gappy.mean(10, 30)).toBeNull()
    expect(gappy.mean(-50, -10)).toBeNull()
    expect(gappy.mean(100, 200)).toBeNull()
  })

  it('cuts a sample short when the next one starts within the interval', () => {
    const series = new StepSeries([[0, 10], [4, 20]], 10)
    expect(series.totalCover).toBe(14)
    expect(series.mean(0, 14)).toBeCloseTo((4 * 10 + 10 * 20) / 14, 10)
  })

  it('returns null for an empty or inverted range and for an empty series', () => {
    const series = new StepSeries(TEN_SECOND_STEPS, 10)
    expect(series.mean(12, 12)).toBeNull()
    expect(series.mean(20, 10)).toBeNull()
    const empty = new StepSeries([], 1)
    expect(empty.mean(0, 10)).toBeNull()
    expect(empty.overallMean).toBe(0)
    expect(empty.valueAt(0)).toBeNull()
  })

  it('agrees with a sample-by-sample reference on irregular series and arbitrary ranges', () => {
    const random = seededRandom(20261113)
    for (let round = 0; round < 40; round++) {
      const points = randomSeries(random, 60)
      const series = new StepSeries(points, 2)
      const last = points[points.length - 1][0]
      for (let query = 0; query < 25; query++) {
        const start = random() * (last + 6) - 3
        const end = start + random() * 30
        const expected = naiveMean(points, 2, start, end)
        const actual = series.mean(start, end)
        if (expected === null) expect(actual).toBeNull()
        else expect(actual).toBeCloseTo(expected, 8)
      }
    }
  })
})

describe('percentDelta', () => {
  it('is the signed percentage of the baseline, rounded to two decimals', () => {
    expect(percentDelta(75, 50)).toBe(50)
    expect(percentDelta(40, 50)).toBe(-20)
    expect(percentDelta(1, 3)).toBe(-66.67)
  })

  it('is zero for a zero baseline and uses the magnitude of a negative one', () => {
    expect(percentDelta(5, 0)).toBe(0)
    expect(percentDelta(-5, -10)).toBe(50)
  })
})
