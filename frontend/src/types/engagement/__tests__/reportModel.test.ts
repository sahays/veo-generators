import { describe, expect, it } from 'vitest'
import type { EngagementReport, SignalPoint } from '@/types/insights'
import { SMOOTHED_KEY, buildCurveRows, drawnSeries, toUnit } from '../curveRows'
import { buildReportModel, displayRange, extremumInContext, extremumTitle, hookWindowSec, nearestExtremum } from '../reportModel'
import { SMALL_REPORT } from './reportFixture'

const model = buildReportModel(SMALL_REPORT)
const FULL_VIEW = { start: 0, end: 45 }

describe('buildReportModel', () => {
  it('indexes extrema by time while the report lists them by kind', () => {
    expect(model.extrema.items.map((extremum) => extremum.id)).toEqual(['valley-1', 'peak-1', 'drop-1'])
    expect([...model.extremumTimes]).toEqual([5, 30, 35])
    expect(model.extremumById.get('drop-1')?.time_sec).toBe(35)
  })

  it('makes every extremum a selectable point item for deep links', () => {
    expect(model.itemRefs.get('peak-1')).toEqual({ kind: 'extremum', id: 'peak-1', label: 'Peak at 0:30', range: { start_sec: 30, end_sec: 30 } })
  })

  it('groups drivers by kind in a fixed order, keeps report order inside a group and omits empty kinds', () => {
    expect(model.influenceGroups.map((group) => group.kind)).toEqual(['character', 'emotion', 'event'])
    expect(model.influenceGroups[0].items.map((driver) => driver.key)).toEqual(['character:asha', 'character:mr. rao'])
  })

  it('knows which extremum window contains a time', () => {
    expect(model.extremumWindows.firstAt(2)?.extremum.id).toBe('valley-1')
    expect(model.extremumWindows.at(31).map((window) => window.extremum.id)).toEqual(['peak-1', 'drop-1'])
  })

  it('resolves overlapping windows to the extremum closest in time, and to none outside every window', () => {
    // 31 s is inside the windows of the peak at 30 s and of the drop at 35 s.
    expect(extremumInContext(model, 31)?.id).toBe('peak-1')
    expect(extremumInContext(model, 34)?.id).toBe('drop-1')
    expect(extremumInContext(model, 2)?.id).toBe('valley-1')
    expect(extremumInContext(model, 20)).toBeNull()
  })

  it('flags smoothing only when the smoothed series differs from the primary metric', () => {
    expect(model.smoothing).toBe(true)
    const unsmoothed: EngagementReport = { ...SMALL_REPORT, smoothed: SMALL_REPORT.metrics[0].points }
    expect(buildReportModel(unsmoothed).smoothing).toBe(false)
  })

  it('falls back to the first metric, then to an empty series, when none is marked primary', () => {
    const noPrimary: EngagementReport = { ...SMALL_REPORT, metrics: SMALL_REPORT.metrics.map((metric) => ({ ...metric, primary: false })) }
    expect(buildReportModel(noPrimary).primary.key).toBe('index')
    const empty = buildReportModel({ ...SMALL_REPORT, metrics: [], smoothed: [], extrema: [] })
    expect(empty.primary.series.size).toBe(0)
    expect(nearestExtremum(empty, 10)).toBeNull()
  })
})

describe('nearestExtremum', () => {
  it('picks the closest extremum in time and the earlier one on a tie', () => {
    expect(nearestExtremum(model, 0)?.id).toBe('valley-1')
    expect(nearestExtremum(model, 17.4)?.id).toBe('valley-1')
    expect(nearestExtremum(model, 17.5)?.id).toBe('valley-1')
    expect(nearestExtremum(model, 17.6)?.id).toBe('peak-1')
    expect(nearestExtremum(model, 33)?.id).toBe('drop-1')
    expect(nearestExtremum(model, 44)?.id).toBe('drop-1')
  })
})

describe('displayRange', () => {
  it('adds headroom around the values but never goes below zero for non-negative data', () => {
    expect(displayRange([[0, 2], [1, 102]])).toEqual([0, 114])
    const [lo, hi] = displayRange([[0, 50], [1, 60]])
    expect(lo).toBeCloseTo(48.8, 10)
    expect(hi).toBeCloseTo(61.2, 10)
  })

  it('still spans a range for a flat series, an all-zero series and negative values', () => {
    expect(displayRange([[0, 40], [1, 40]])).toEqual([35.2, 44.8])
    expect(displayRange([[0, 0]])).toEqual([0, 1])
    expect(displayRange([[0, -10], [1, 10]])).toEqual([-12.4, 12.4])
    expect(displayRange([])).toEqual([0, 1])
  })
})

describe('drawnSeries', () => {
  it('draws every metric on its own scale plus the smoothed primary', () => {
    const drawn = drawnSeries(model, [], true)
    expect(drawn.map((series) => [series.key, series.role])).toEqual([['m0', 'primary'], ['m1', 'secondary'], [SMOOTHED_KEY, 'smoothed']])
    expect(drawn[0].hi).toBeLessThan(drawn[1].lo)
    expect(drawn[2].lo).toBe(drawn[0].lo)
  })

  it('leaves out hidden metrics, and the smoothed line with its metric', () => {
    expect(drawnSeries(model, ['reach'], true).map((series) => series.key)).toEqual(['m0', SMOOTHED_KEY])
    expect(drawnSeries(model, ['index'], true).map((series) => series.key)).toEqual(['m1'])
    expect(drawnSeries(model, [], false).map((series) => series.key)).toEqual(['m0', 'm1'])
  })
})

describe('buildCurveRows', () => {
  it('merges series on time, scales each to 0..1 of its own range and closes the last step', () => {
    const rows = buildCurveRows(drawnSeries(model, [], false), FULL_VIEW, 1000)
    expect(rows.map((row) => row.t)).toEqual([0, 5, 10, 15, 20, 25, 30, 35, 40, 45])
    const { lo, hi } = model.primary
    expect(rows[6].m0).toBeCloseTo(toUnit(90, lo, hi), 10)
    // Both metrics have the same shape, so on their own scales they land on the same height.
    expect(rows[6].m1).toBeCloseTo(rows[6].m0, 10)
    expect(rows[9]).toEqual({ t: 45, m0: rows[8].m0, m1: rows[8].m1 })
    rows.forEach((row) => expect(row.m0).toBeGreaterThanOrEqual(0))
    rows.forEach((row) => expect(row.m0).toBeLessThanOrEqual(1))
  })

  it('leaves a series out of the rows where it has no sample', () => {
    const sparse = [{ key: 'a', points: [[0, 1], [10, 2]] as SignalPoint[], lo: 0, hi: 2 }, { key: 'b', points: [[5, 4]] as SignalPoint[], lo: 0, hi: 4 }]
    expect(buildCurveRows(sparse, { start: 0, end: 20 }, 500)).toEqual([{ t: 0, a: 0.5 }, { t: 5, b: 1 }, { t: 10, a: 1 }])
  })

  it('keeps one neighbour outside the view, and only closes the series when its last sample is drawn', () => {
    const rows = buildCurveRows(drawnSeries(model, ['reach'], false), { start: 12, end: 22 }, 400)
    expect(rows.map((row) => row.t)).toEqual([10, 15, 20, 25])
  })

  it('reduces a dense series to about a point per pixel without losing its peak', () => {
    const dense: SignalPoint[] = Array.from({ length: 20000 }, (_, i) => [i, i === 12345 ? 999 : (i % 7) + 1])
    const rows = buildCurveRows([{ key: 'a', points: dense, lo: 0, hi: 1000 }], { start: 0, end: 20000 }, 300)
    expect(rows.length).toBeLessThanOrEqual(300)
    expect(Math.max(...rows.map((row) => row.a))).toBeCloseTo(0.999, 10)
  })
})

describe('labels', () => {
  it('titles an extremum without prose by its kind and time', () => {
    expect(extremumTitle(SMALL_REPORT.extrema[1])).toBe('Valley at 0:05')
    expect(extremumTitle({ ...SMALL_REPORT.extrema[0], title: 'The joke lands' })).toBe('The joke lands')
  })

  it('measures the hook over a tenth of the video, at most 15 seconds', () => {
    expect(hookWindowSec(45)).toBe(4.5)
    expect(hookWindowSec(3600)).toBe(15)
    expect(hookWindowSec(-1)).toBe(0)
  })
})
