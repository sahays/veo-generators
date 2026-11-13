import { describe, expect, it } from 'vitest'
import type { TimeRange } from '@/types/insights'
import { lowerBound, upperBound } from '../bisect'
import { IntervalIndex, PointIndex } from '../intervalIndex'

interface Item extends TimeRange {
  id: string
}

const item = (id: string, start_sec: number, end_sec: number): Item => ({ id, start_sec, end_sec })
const ids = (items: readonly Item[]): string[] => items.map((i) => i.id)

/** Deterministic PRNG so the randomised comparison is reproducible. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

describe('bisect', () => {
  it('finds insertion points with duplicates', () => {
    const values = [1, 2, 2, 2, 5]
    expect(lowerBound(values, 2)).toBe(1)
    expect(upperBound(values, 2)).toBe(4)
    expect(lowerBound(values, 0)).toBe(0)
    expect(upperBound(values, 9)).toBe(5)
    expect(lowerBound([], 3)).toBe(0)
  })
})

describe('IntervalIndex', () => {
  const segments = new IntervalIndex([item('b', 10, 20), item('a', 0, 10), item('c', 20, 30)])

  it('treats ranges as half-open so adjacent items never both match', () => {
    expect(ids(segments.at(10))).toEqual(['b'])
    expect(ids(segments.at(9.999))).toEqual(['a'])
    expect(ids(segments.at(30))).toEqual([])
    expect(ids(segments.at(-1))).toEqual([])
  })

  it('returns items overlapping a window and excludes ones that only touch it', () => {
    expect(ids(segments.overlapping(5, 15))).toEqual(['a', 'b'])
    expect(ids(segments.overlapping(10, 20))).toEqual(['b'])
    expect(ids(segments.overlapping(30, 40))).toEqual([])
    expect(ids(segments.overlapping(-5, 0))).toEqual([])
  })

  it('finds a long item that started far before the query window', () => {
    // 'music' starts first and outlives many short cues; a search that only
    // looked near the query time would miss it.
    const cues = new IntervalIndex([
      item('music', 0, 100),
      item('c1', 1, 2),
      item('c2', 3, 4),
      item('c3', 5, 6),
      item('c4', 50, 51),
    ])
    expect(ids(cues.at(70))).toEqual(['music'])
    expect(ids(cues.overlapping(49, 52))).toEqual(['music', 'c4'])
    expect(cues.firstAt(50.5)?.id).toBe('c4')
    expect(cues.firstAt(70)?.id).toBe('music')
  })

  it('navigates to the next and previous item by start time', () => {
    expect(segments.next(10)?.id).toBe('c')
    expect(segments.next(9.9)?.id).toBe('b')
    expect(segments.next(25)).toBeNull()
    expect(segments.previous(10)?.id).toBe('a')
    expect(segments.previous(10.1)?.id).toBe('b')
    expect(segments.previous(0)).toBeNull()
  })

  it('ignores zero-length items and handles an empty index', () => {
    const index = new IntervalIndex([item('zero', 5, 5), item('real', 4, 6)])
    expect(ids(index.at(5))).toEqual(['real'])
    const empty = new IntervalIndex<Item>([])
    expect(empty.at(1)).toEqual([])
    expect(empty.overlapping(0, 10)).toEqual([])
    expect(empty.firstAt(1)).toBeNull()
  })

  it('agrees with a linear scan on random overlapping intervals', () => {
    const random = mulberry32(42)
    const items = Array.from({ length: 400 }, (_, i) => {
      const start = random() * 1000
      return item(`r${i}`, start, start + random() * (i % 7 === 0 ? 300 : 12))
    })
    const index = new IntervalIndex(items)
    const sorted = [...index.items]
    for (let q = 0; q < 300; q++) {
      const a = random() * 1100 - 50
      const b = a + random() * 40
      expect(ids(index.at(a))).toEqual(ids(sorted.filter((i) => i.start_sec <= a && a < i.end_sec)))
      expect(ids(index.overlapping(a, b))).toEqual(ids(sorted.filter((i) => i.start_sec < b && i.end_sec > a)))
    }
  })
})

describe('PointIndex', () => {
  const points = new PointIndex([{ start_sec: 5 }, { start_sec: 1 }, { start_sec: 9 }, { start_sec: 5 }])

  it('returns markers in a half-open window', () => {
    expect(points.between(1, 5).map((p) => p.start_sec)).toEqual([1])
    expect(points.between(5, 9.01).map((p) => p.start_sec)).toEqual([5, 5, 9])
    expect(points.between(10, 20)).toEqual([])
  })

  it('finds the latest marker at or before a time', () => {
    expect(points.lastAtOrBefore(0.5)).toBeNull()
    expect(points.lastAtOrBefore(5)?.start_sec).toBe(5)
    expect(points.lastAtOrBefore(100)?.start_sec).toBe(9)
  })
})
