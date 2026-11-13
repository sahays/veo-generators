import { describe, expect, it } from 'vitest'
import { IntervalIndex } from '../intervalIndex'
import { emotionIntensitySeries } from '../series'
import { fitLabel, segmentJumpTarget, shortcutForKey } from '../shortcuts'
import { matchesQuery, splitHighlight } from '../textSearch'
import { AD_SPOT_TIMELINE } from './adSpotFixture'

describe('splitHighlight', () => {
  it('marks every occurrence, ignoring case, and keeps the original text', () => {
    const parts = splitHighlight('Kadak Chai. Made strong, kadak ho.', 'KADAK')
    expect(parts).toEqual([
      { text: 'Kadak', match: true },
      { text: ' Chai. Made strong, ', match: false },
      { text: 'kadak', match: true },
      { text: ' ho.', match: false },
    ])
    expect(parts.map((p) => p.text).join('')).toBe('Kadak Chai. Made strong, kadak ho.')
  })

  it('treats the query literally, including pattern characters', () => {
    expect(splitHighlight('cost (approx.) $5', '(approx.)')[1]).toEqual({ text: '(approx.)', match: true })
    expect(splitHighlight('a.b', '.*').some((p) => p.match)).toBe(false)
  })

  it('returns one plain part for an empty query and nothing for empty text', () => {
    expect(splitHighlight('hello', '   ')).toEqual([{ text: 'hello', match: false }])
    expect(splitHighlight('', 'x')).toEqual([])
    expect(splitHighlight('aaa', 'aa')).toEqual([
      { text: 'aa', match: true },
      { text: 'a', match: false },
    ])
  })

  it('matches a query against any of several optional fields', () => {
    expect(matchesQuery('rao', 'Come in', 'Mr. Rao')).toBe(true)
    expect(matchesQuery('rao', 'Come in', undefined)).toBe(false)
    expect(matchesQuery('  ', undefined)).toBe(true)
  })
})

describe('player shortcuts', () => {
  const segments = new IntervalIndex(AD_SPOT_TIMELINE.segments)

  it('maps keys to actions regardless of case and ignores other keys', () => {
    expect(shortcutForKey(' ')).toEqual({ type: 'toggle' })
    expect(shortcutForKey('K')).toEqual({ type: 'toggle' })
    expect(shortcutForKey('ArrowLeft')).toEqual({ type: 'step', deltaSec: -5 })
    expect(shortcutForKey('l')).toEqual({ type: 'step', deltaSec: 10 })
    expect(shortcutForKey(']')).toEqual({ type: 'segment', direction: 1 })
    expect(shortcutForKey('a')).toBeNull()
    expect(shortcutForKey('Enter')).toBeNull()
  })

  it('jumps to the next segment start and stops at the last one', () => {
    expect(segmentJumpTarget(segments, 8, 1)).toBe(12)
    expect(segmentJumpTarget(segments, 12, 1)).toBe(17.4)
    expect(segmentJumpTarget(segments, 44, 1)).toBeNull()
  })

  it('restarts the current segment, or goes one back when pressed at its start', () => {
    expect(segmentJumpTarget(segments, 10, -1)).toBe(7.5)
    expect(segmentJumpTarget(segments, 7.8, -1)).toBe(3.2)
    expect(segmentJumpTarget(segments, 0.2, -1)).toBe(0)
    expect(segmentJumpTarget(new IntervalIndex([]), 5, -1)).toBeNull()
  })

  it('fits labels to the available width', () => {
    expect(fitLabel('Kettle', 100)).toBe('Kettle')
    expect(fitLabel('The kettle goes on', 62)).toBe('The kettl…')
    expect(fitLabel('The kettle goes on', 12)).toBe('')
  })
})

describe('emotionIntensitySeries', () => {
  const emotions = new IntervalIndex(AD_SPOT_TIMELINE.emotions)

  it('samples the strongest emotion at each bin centre without averaging spans', () => {
    const series = emotionIntensitySeries(emotions, 45, 90)
    expect(series).toHaveLength(90)
    expect(series[0]).toEqual({ time: 0.25, intensity: 0.35, emotion: 'calm' })
    // 30.25 s: humor (0.8) and joy (0.7) overlap; the stronger one wins outright.
    expect(series.find((s) => s.time === 30.25)).toEqual({ time: 30.25, intensity: 0.8, emotion: 'humor' })
    expect(series.find((s) => s.time === 36.25)).toEqual({ time: 36.25, intensity: 0.9, emotion: 'triumph' })
    expect(series.every((s, i) => i === 0 || s.time > series[i - 1].time)).toBe(true)
  })

  it('reports zero where nothing is tagged and handles degenerate input', () => {
    const sparse = new IntervalIndex([{ id: 'emo-1', start_sec: 4, end_sec: 6, emotion: 'joy', intensity: 0.6 }])
    const series = emotionIntensitySeries(sparse, 10, 5)
    expect(series.map((s) => s.intensity)).toEqual([0, 0, 0.6, 0, 0])
    expect(series[0].emotion).toBeNull()
    expect(emotionIntensitySeries(sparse, 0)).toEqual([])
    expect(emotionIntensitySeries(sparse, 0.2, 120)).toHaveLength(1)
  })
})
