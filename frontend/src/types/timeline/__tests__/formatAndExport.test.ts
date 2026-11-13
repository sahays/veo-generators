import { describe, expect, it } from 'vitest'
import type { TimelineCue } from '@/types/insights'
import { coverageBins, downsampleForView, downsampleMinMax, sliceVisible, type SeriesPoint } from '../downsample'
import { cuesToSrt, cuesToVtt, escapeCsvCell, exportFileStem, timelineCollectionCsv, toCsv } from '../exporters'
import { formatSpan, formatSubtitleTime, formatTimecode, parseTimeParam, toTimeParam } from '../timeFormat'
import { AD_SPOT_TIMELINE } from './adSpotFixture'

describe('time formatting', () => {
  it('formats player timecodes with and without tenths', () => {
    expect(formatTimecode(7)).toBe('0:07')
    expect(formatTimecode(754.9)).toBe('12:34')
    expect(formatTimecode(3723)).toBe('1:02:03')
    expect(formatTimecode(7.56, { tenths: true })).toBe('0:07.5')
    expect(formatTimecode(-3)).toBe('0:00')
    expect(formatTimecode(Number.NaN)).toBe('0:00')
  })

  it('does not show 0:60 just below a minute boundary', () => {
    expect(formatTimecode(59.99)).toBe('0:59')
    expect(formatTimecode(59.99, { tenths: true })).toBe('0:59.9')
  })

  it('formats spans and subtitle timestamps', () => {
    expect(formatSpan(0.84)).toBe('0.8s')
    expect(formatSpan(45)).toBe('45s')
    expect(formatSpan(65)).toBe('1m 05s')
    expect(formatSpan(3725)).toBe('1h 02m')
    expect(formatSubtitleTime(3661.5, ',')).toBe('01:01:01,500')
    expect(formatSubtitleTime(0.0996, '.')).toBe('00:00:00.100')
  })

  it('parses ?t= values and rejects anything that is not a time', () => {
    expect(parseTimeParam('12.5')).toBe(12.5)
    expect(parseTimeParam('1:05')).toBe(65)
    expect(parseTimeParam('1:02:03')).toBe(3723)
    expect(parseTimeParam(' 7 ')).toBe(7)
    expect(parseTimeParam('-4')).toBeNull()
    expect(parseTimeParam('abc')).toBeNull()
    expect(parseTimeParam('1e3')).toBeNull()
    expect(parseTimeParam('')).toBeNull()
    expect(parseTimeParam(null)).toBeNull()
    expect(toTimeParam(12.345)).toBe('12.3')
    expect(parseTimeParam(toTimeParam(20.6))).toBe(20.6)
  })
})

describe('downsampling', () => {
  const series: SeriesPoint[] = Array.from({ length: 1000 }, (_, i) => [i, Math.sin(i / 25) * 10])

  it('keeps one neighbour on each side of the viewport', () => {
    const visible = sliceVisible(series, { start: 100.5, end: 103.5 })
    expect(visible.map((p) => p[0])).toEqual([100, 101, 102, 103, 104])
    expect(sliceVisible(series, { start: 2000, end: 3000 }).map((p) => p[0])).toEqual([999])
  })

  it('respects the point budget and stays in time order', () => {
    const reduced = downsampleMinMax(series, 100)
    expect(reduced.length).toBeLessThanOrEqual(100)
    expect(reduced.length).toBeGreaterThan(40)
    expect(reduced.every((p, i) => i === 0 || p[0] > reduced[i - 1][0])).toBe(true)
  })

  it('preserves a single-sample spike and the overall extremes', () => {
    const spiky: SeriesPoint[] = series.map((p) => (p[0] === 617 ? [617, 500] : p[0] === 302 ? [302, -500] : p))
    const values = downsampleMinMax(spiky, 60).map((p) => p[1])
    expect(Math.max(...values)).toBe(500)
    expect(Math.min(...values)).toBe(-500)
  })

  it('returns short series untouched and reduces to about one point per pixel', () => {
    expect(downsampleMinMax(series.slice(0, 10), 100)).toHaveLength(10)
    const forView = downsampleForView(series, { start: 0, end: 999 }, 300)
    expect(forView.length).toBeLessThanOrEqual(300)
    expect(forView.length).toBeGreaterThanOrEqual(150)
  })

  it('computes how much of each bin is covered', () => {
    const ranges = [
      { start_sec: 0, end_sec: 5 },
      { start_sec: 2.5, end_sec: 5 },
      { start_sec: 12.5, end_sec: 30 },
    ]
    expect(coverageBins(ranges, { start: 0, end: 20 }, 4)).toEqual([1, 0, 0.5, 1])
    expect(coverageBins(ranges, { start: 0, end: 0 }, 4)).toEqual([0, 0, 0, 0])
  })
})

const cue = (overrides: Partial<TimelineCue>): TimelineCue => ({
  id: 'cue-1',
  start_sec: 0,
  end_sec: 1,
  text: 'Hello',
  kind: 'dialogue',
  ...overrides,
})

describe('subtitle export', () => {
  const cues = [
    cue({ id: 'cue-1', start_sec: 1.1, end_sec: 3, speaker: 'Narrator', text: 'Some evenings\n\narrive all at once.', kind: 'narration' }),
    cue({ id: 'cue-2', start_sec: 3.4, end_sec: 4.6, text: 'Door creaks', kind: 'sfx' }),
    cue({ id: 'cue-3', start_sec: 5, end_sec: 6, text: 'Quiet', kind: 'silence' }),
    cue({ id: 'cue-4', start_sec: 7, end_sec: 7, speaker: 'A <b>', text: 'x < y --> z & more' }),
  ]

  it('writes numbered SRT blocks, skipping silence and collapsing blank lines', () => {
    expect(cuesToSrt(cues)).toBe(
      [
        '1\n00:00:01,100 --> 00:00:03,000\nNarrator: Some evenings\narrive all at once.\n',
        '2\n00:00:03,400 --> 00:00:04,600\n[Door creaks]\n',
        '3\n00:00:07,000 --> 00:00:07,050\nA <b>: x < y --> z & more\n',
      ].join('\n'),
    )
  })

  it('writes WebVTT with voice spans and escaped markup', () => {
    const vtt = cuesToVtt(cues)
    expect(vtt.startsWith('WEBVTT\n\ncue-1\n00:00:01.100 --> 00:00:03.000\n<v Narrator>Some evenings\narrive')).toBe(true)
    expect(vtt).toContain('cue-4\n00:00:07.000 --> 00:00:07.050\n<v A &lt;b&gt;>x &lt; y --&gt; z &amp; more\n')
    expect(vtt).not.toContain('Quiet')
  })

  it('exports every spoken or sound cue of the fixture', () => {
    const blocks = cuesToSrt(AD_SPOT_TIMELINE.cues).trim().split('\n\n')
    expect(blocks).toHaveLength(AD_SPOT_TIMELINE.cues.filter((c) => c.kind !== 'silence').length)
    expect(blocks[blocks.length - 1].split('\n')[1]).toBe('00:00:43,000 --> 00:00:45,000')
  })
})

describe('CSV export', () => {
  it('neutralises cells a spreadsheet would run as formulas', () => {
    expect(escapeCsvCell('=SUM(A1:A9)')).toBe("'=SUM(A1:A9)")
    expect(escapeCsvCell('+1 555 0100')).toBe("'+1 555 0100")
    expect(escapeCsvCell('-2+3')).toBe("'-2+3")
    expect(escapeCsvCell('@import')).toBe("'@import")
    expect(escapeCsvCell('  =HYPERLINK("http://x","y")')).toBe('"\'  =HYPERLINK(""http://x"",""y"")"')
    expect(escapeCsvCell('\tcmd')).toBe("'\tcmd")
  })

  it('leaves numbers, booleans and ordinary text alone', () => {
    expect(escapeCsvCell(-3.2)).toBe('-3.2')
    expect(escapeCsvCell(true)).toBe('true')
    expect(escapeCsvCell(null)).toBe('')
    expect(escapeCsvCell(undefined)).toBe('')
    expect(escapeCsvCell('a = b')).toBe('a = b')
    expect(escapeCsvCell('Tea, strong')).toBe('"Tea, strong"')
    expect(escapeCsvCell('He said "hi"\nbye')).toBe('"He said ""hi""\nbye"')
  })

  it('builds CRLF-terminated rows', () => {
    expect(toCsv(['id', 'text'], [['a', '=1'], ['b', 2]])).toBe("id,text\r\na,'=1\r\nb,2\r\n")
  })

  it('exports one row per entity appearance with a header', () => {
    const lines = timelineCollectionCsv(AD_SPOT_TIMELINE, 'entities').trim().split('\r\n')
    const appearances = AD_SPOT_TIMELINE.entities.reduce((n, e) => n + e.appearances.length, 0)
    expect(lines[0]).toBe('id,name,kind,description,screen_time_sec,appearance_start_sec,appearance_end_sec')
    expect(lines).toHaveLength(appearances + 1)
    expect(lines[1]).toBe('ent-1,Asha,character,"Woman in her late twenties, office wear, wet hair.",24.9,3.2,12')
  })

  it('derives a safe file stem', () => {
    expect(exportFileStem('Kadak Chai — Monsoon (45s).mp4')).toBe('kadak-chai-monsoon-45s')
    expect(exportFileStem('../../etc/passwd')).toBe('etc-passwd')
    expect(exportFileStem('   ')).toBe('timeline')
  })
})
