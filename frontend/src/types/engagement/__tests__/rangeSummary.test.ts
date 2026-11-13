import { describe, expect, it } from 'vitest'
import { buildTimelineModel } from '@/types/timeline/model'
import { AD_SPOT_TIMELINE } from '@/types/timeline/__tests__/adSpotFixture'
import { summariseRange } from '../rangeSummary'
import { buildReportModel } from '../reportModel'
import { SMALL_REPORT } from './reportFixture'

const report = buildReportModel(SMALL_REPORT)
const timeline = buildTimelineModel(AD_SPOT_TIMELINE)

describe('summariseRange', () => {
  it('averages the primary metric over the range, weighting partial samples, against the overall average', () => {
    // 2 s of 60 (15-20), 5 s of 70, 5 s of 65, 2 s of 90 (30-35).
    const summary = summariseRange(report, timeline, { start_sec: 18, end_sec: 32 })
    const expected = (2 * 60 + 5 * 70 + 5 * 65 + 2 * 90) / 14
    expect(summary.average).toBeCloseTo(expected, 10)
    expect(summary.coveredSec).toBeCloseTo(14, 10)
    expect(summary.deltaPct).toBeCloseTo(Math.round(((expected - 53.33) / 53.33) * 10000) / 100, 10)
  })

  it('lists who is on screen with the seconds inside the range, longest first', () => {
    const summary = summariseRange(report, timeline, { start_sec: 18, end_sec: 32 })
    const present = summary.entities.map(({ entity, seconds }) => [entity.name, Math.round(seconds * 10) / 10])
    // Asha is on screen throughout; Mr. Rao arrives at 23.4; the pack shows 20.5-22.8 only.
    expect(present.slice(0, 3)).toEqual([['Asha', 14], ['Steel tumblers', 8.8], ['Mr. Rao', 8.6]])
    expect(present).toContainEqual(['Kadak Chai pack', 2.3])
    expect(present.map(([name]) => name)).not.toContain('Offer QR code')
  })

  it('lists the cues and segments that overlap the range', () => {
    const summary = summariseRange(report, timeline, { start_sec: 23, end_sec: 27 })
    expect(summary.cues.map((cue) => cue.id)).toEqual(['cue-11', 'cue-12', 'cue-13'])
    expect(summary.segments.map((segment) => segment.id)).toEqual(['seg-6'])
  })

  it('reports no average where the signal has no samples', () => {
    const late = buildReportModel({ ...SMALL_REPORT, metrics: [{ key: 'index', label: 'Index', primary: true, points: [[30, 10], [35, 20]] }] })
    const summary = summariseRange(late, timeline, { start_sec: 0, end_sec: 12 })
    expect(summary.average).toBeNull()
    expect(summary.deltaPct).toBeNull()
    expect(summary.coveredSec).toBe(0)
    expect(summary.entities.length).toBeGreaterThan(0)
  })
})
