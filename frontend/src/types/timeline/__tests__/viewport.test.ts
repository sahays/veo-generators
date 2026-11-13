import { describe, expect, it } from 'vitest'
import { buildTicks, pickTickStep } from '../ticks'
import {
  clampViewport,
  createTimeScale,
  fitViewport,
  isFitted,
  panViewport,
  revealTime,
  viewportForRange,
  zoomViewport,
} from '../viewport'

describe('clampViewport', () => {
  it('slides a range that overshoots an edge back inside, keeping its span', () => {
    expect(clampViewport({ start: 40, end: 70 }, 60)).toEqual({ start: 30, end: 60 })
    expect(clampViewport({ start: -10, end: 5 }, 60)).toEqual({ start: 0, end: 15 })
  })

  it('enforces the minimum span and never exceeds the duration', () => {
    const tiny = clampViewport({ start: 10, end: 10.01 }, 60)
    expect(tiny.end - tiny.start).toBeCloseTo(1)
    expect(clampViewport({ start: -100, end: 500 }, 60)).toEqual({ start: 0, end: 60 })
  })

  it('copes with reversed, non-finite and zero-duration input', () => {
    expect(clampViewport({ start: 30, end: 10 }, 60)).toEqual({ start: 10, end: 30 })
    expect(clampViewport({ start: NaN, end: NaN }, 60)).toEqual({ start: 0, end: 60 })
    expect(clampViewport({ start: 3, end: 9 }, 0)).toEqual({ start: 0, end: 0 })
  })

  it('lets a clip shorter than the minimum span fill the view', () => {
    expect(clampViewport({ start: 0.1, end: 0.2 }, 0.5)).toEqual({ start: 0, end: 0.5 })
  })
})

describe('zoomViewport', () => {
  it('keeps the time under the cursor at the same pixel', () => {
    const view = { start: 10, end: 50 }
    const width = 800
    const anchor = 22
    const before = createTimeScale(view, width).toX(anchor)
    const zoomed = zoomViewport(view, 2, anchor, 120)
    expect(zoomed.end - zoomed.start).toBeCloseTo(20)
    expect(createTimeScale(zoomed, width).toX(anchor)).toBeCloseTo(before)
  })

  it('stops at the full duration when zooming out and at the minimum span when zooming in', () => {
    expect(zoomViewport({ start: 10, end: 50 }, 0.01, 30, 120)).toEqual({ start: 0, end: 120 })
    const deep = zoomViewport({ start: 10, end: 12 }, 1000, 11, 120)
    expect(deep.end - deep.start).toBeCloseTo(1)
    expect(deep.start).toBeLessThanOrEqual(11)
    expect(deep.end).toBeGreaterThanOrEqual(11)
  })

  it('still returns a valid viewport when the anchor sits at the edge of the video', () => {
    const zoomed = zoomViewport({ start: 0, end: 60 }, 4, 60, 60)
    expect(zoomed).toEqual({ start: 45, end: 60 })
  })

  it('ignores a non-positive factor', () => {
    expect(zoomViewport({ start: 10, end: 50 }, 0, 30, 120)).toEqual({ start: 10, end: 50 })
  })
})

describe('pan, reveal and range helpers', () => {
  it('pans without changing the span and stops at the edges', () => {
    expect(panViewport({ start: 10, end: 30 }, 5, 60)).toEqual({ start: 15, end: 35 })
    expect(panViewport({ start: 10, end: 30 }, 500, 60)).toEqual({ start: 40, end: 60 })
    expect(panViewport({ start: 10, end: 30 }, -500, 60)).toEqual({ start: 0, end: 20 })
  })

  it('returns the same viewport object when the time is already visible', () => {
    const view = { start: 10, end: 30 }
    expect(revealTime(view, 12, 60)).toBe(view)
    expect(revealTime(view, 31, 60)).toEqual({ start: 29, end: 49 })
    expect(revealTime(view, 59, 60)).toEqual({ start: 40, end: 60 })
  })

  it('pads a range and reports whether the whole video is shown', () => {
    expect(viewportForRange({ start: 20, end: 30 }, 100, 0.1)).toEqual({ start: 19, end: 31 })
    expect(isFitted(fitViewport(45), 45)).toBe(true)
    expect(isFitted({ start: 0, end: 44 }, 45)).toBe(false)
  })
})

describe('createTimeScale', () => {
  it('round-trips between time and pixels', () => {
    const scale = createTimeScale({ start: 5, end: 25 }, 1000)
    expect(scale.pxPerSec).toBe(50)
    expect(scale.toX(5)).toBe(0)
    expect(scale.toX(25)).toBe(1000)
    expect(scale.toTime(scale.toX(13.37))).toBeCloseTo(13.37)
  })

  it('does not divide by zero for an unmeasured or empty plot', () => {
    const scale = createTimeScale({ start: 5, end: 5 }, 0)
    expect(scale.toX(7)).toBe(0)
    expect(scale.toTime(120)).toBe(5)
  })
})

describe('ruler ticks', () => {
  it('picks the smallest step that keeps labels apart', () => {
    expect(pickTickStep(45, 900, 72)).toBe(5)
    expect(pickTickStep(3, 900, 72)).toBe(0.5)
    expect(pickTickStep(7200, 900, 72)).toBe(600)
    expect(pickTickStep(0, 900)).toBe(7200)
  })

  it('emits majors on the step grid inside the viewport, without float drift', () => {
    const ticks = buildTicks({ start: 0.25, end: 2.05 }, 1200, 72)
    expect(ticks.step).toBe(0.2)
    expect(ticks.major).toEqual([0.4, 0.6, 0.8, 1, 1.2, 1.4, 1.6, 1.8, 2])
  })

  it('never repeats a major tick as a minor tick', () => {
    const ticks = buildTicks({ start: 0, end: 45 }, 900, 72)
    expect(ticks.major).toEqual([0, 5, 10, 15, 20, 25, 30, 35, 40, 45])
    expect(ticks.minor).toContain(1)
    expect(ticks.minor.filter((t) => ticks.major.includes(t))).toEqual([])
    expect(ticks.minor).toHaveLength(36)
  })
})
