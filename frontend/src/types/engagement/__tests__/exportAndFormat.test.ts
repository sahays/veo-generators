import { describe, expect, it } from 'vitest'
import type { EngagementReport, EngagementSignalSpec } from '@/types/insights'
import { curveCsv, curveTable, driversCsv, extremaCsv } from '../reportExport'
import { describeDelta, driverLabel, engagementRecordName, formatAxisValue, formatDelta, formatValue, reportBadgeText, signalBadgeText } from '../reportFormat'
import { SMALL_REPORT } from './reportFixture'

const lines = (csv: string): string[] => csv.split('\r\n')

describe('curve export', () => {
  it('writes one row per sample time with every metric and the smoothed primary', () => {
    const rows = lines(curveCsv(SMALL_REPORT))
    expect(rows[0]).toBe('time_sec,Index,Reach,Index (smoothed)')
    expect(rows[1]).toBe('0,40,5000,35')
    expect(rows[7]).toBe('30,90,10000,70')
    // Header, nine samples and the terminating line break.
    expect(rows).toHaveLength(11)
    expect(rows[10]).toBe('')
  })

  it('leaves a cell empty where a series has no sample and keeps rows in time order', () => {
    const ragged: EngagementReport = {
      ...SMALL_REPORT,
      metrics: [
        { key: 'a', label: 'A', primary: true, points: [[10, 1], [0, 2]] },
        { key: 'b', label: 'B', primary: false, points: [[5, 3]] },
      ],
      smoothed: [[0, 2]],
    }
    expect(curveTable(ragged).rows).toEqual([[0, 2, null, 2], [5, null, 3, null], [10, 1, null, null]])
    expect(lines(curveCsv(ragged)).slice(1, 4)).toEqual(['0,2,,2', '5,,3,', '10,1,,'])
  })

  it('neutralises metric labels a spreadsheet would run as a formula', () => {
    const hostile: EngagementReport = { ...SMALL_REPORT, metrics: [{ key: 'x', label: '=HYPERLINK("http://evil")', primary: true, points: [[0, 1]] }], smoothed: [] }
    const header = lines(curveCsv(hostile))[0]
    expect(header.startsWith(`time_sec,"'=HYPERLINK(""http://evil"")"`)).toBe(true)
  })
})

describe('extrema and driver exports', () => {
  it('writes the figures, the context window and the prose of each extremum', () => {
    const withProse: EngagementReport = { ...SMALL_REPORT, extrema: [{ ...SMALL_REPORT.extrema[0], title: 'The joke lands', explanation: 'Laughter, then a cut', drivers: ['Mr. Rao', 'humor'] }] }
    const rows = lines(extremaCsv(withProse))
    expect(rows[0]).toBe('id,kind,time_sec,value,delta_pct,prominence,window_start_sec,window_end_sec,segment_id,title,explanation,drivers')
    expect(rows[1]).toBe('peak-1,peak,30,70,31.26,10,25,40,seg-7,The joke lands,"Laughter, then a cut",Mr. Rao; humor')
  })

  it('writes every driver with its support flag and its ranges, guarding names against formula injection', () => {
    const hostile: EngagementReport = { ...SMALL_REPORT, influence: [{ ...SMALL_REPORT.influence[3], name: '+SUM(A1:A9)' }] }
    const rows = lines(driversCsv(hostile))
    expect(rows[0]).toBe('key,name,kind,avg_during,delta_pct,coverage_sec,coverage_pct,low_support,ranges_sec')
    expect(rows[1].startsWith("character:mr. rao,'+SUM(A1:A9),character,")).toBe(true)
    expect(rows[1].endsWith(',8,2,4.44,true,10-20; 30-40')).toBe(true)
    expect(lines(driversCsv(SMALL_REPORT))).toHaveLength(SMALL_REPORT.influence.length + 2)
  })
})

describe('formatValue', () => {
  it('uses fewer decimals for larger numbers and thousands separators', () => {
    expect(formatValue(0.4237)).toBe('0.42')
    expect(formatValue(61.249)).toBe('61.2')
    expect(formatValue(1234.5)).toBe('1,235')
    expect(formatValue(-18.44)).toBe('-18.4')
  })

  it('keeps trailing zeros so readings of one metric line up, but not on axis ticks', () => {
    expect(formatValue(1.4)).toBe('1.40')
    expect(formatValue(63)).toBe('63.0')
    expect(formatValue(0)).toBe('0.00')
    expect(formatAxisValue(1.2)).toBe('1.2')
    expect(formatAxisValue(0)).toBe('0')
    expect(formatAxisValue(25)).toBe('25')
    expect(formatAxisValue(1200)).toBe('1,200')
  })

  it('appends the percent unit, ignores other units and shows a dash for missing values', () => {
    expect(formatValue(0.47, '%')).toBe('0.47%')
    expect(formatValue(61.2, 'index')).toBe('61.2')
    expect(formatValue(null)).toBe('—')
    expect(formatValue(undefined, '%')).toBe('—')
    expect(formatValue(Number.NaN)).toBe('—')
  })
})

describe('formatDelta', () => {
  it('signs the percentage and drops decimals from three-digit values', () => {
    expect(formatDelta(12.34)).toBe('+12.3%')
    expect(formatDelta(-4.06)).toBe('\u22124.1%')
    expect(formatDelta(159.81)).toBe('+160%')
    expect(formatDelta(0.04)).toBe('0%')
    expect(formatDelta(null)).toBe('—')
  })

  it('has a spoken form for accessible names', () => {
    expect(describeDelta(12.34)).toBe('12.3% above average')
    expect(describeDelta(-51.82)).toBe('51.8% below average')
    expect(describeDelta(0)).toBe('at the average')
  })
})

describe('signal badges', () => {
  const labels = new Map([['slow_burn', 'Slow burn']])

  it('always calls a template simulated and names it by label, falling back to its id', () => {
    const template: EngagementSignalSpec = { kind: 'template', template_id: 'slow_burn' }
    expect(signalBadgeText(template, labels)).toEqual({ simulated: true, kind: 'Template (simulated)', detail: 'Slow burn' })
    expect(signalBadgeText({ kind: 'template', template_id: 'front_loaded' }, new Map()).detail).toBe('Front loaded')
  })

  it('names a BARC signal by its file', () => {
    const barc: EngagementSignalSpec = { kind: 'barc', template_id: null, csv_filename: 'week-28.csv' }
    expect(signalBadgeText(barc, labels)).toEqual({ simulated: false, kind: 'BARC', detail: 'week-28.csv' })
    expect(reportBadgeText(SMALL_REPORT.signal)).toEqual({ simulated: false, kind: 'BARC', detail: 'ratings.csv' })
    expect(reportBadgeText({ ...SMALL_REPORT.signal, simulated: true, label: 'Jumpy' }).kind).toBe('Template (simulated)')
  })

  it('humanises emotion names and event tags but leaves entity names as written', () => {
    expect(driverLabel({ name: 'call_to_action', kind: 'event' })).toBe('Call to action')
    expect(driverLabel({ name: 'humor', kind: 'emotion' })).toBe('Humor')
    expect(driverLabel({ name: 'Mr. Rao', kind: 'character' })).toBe('Mr. Rao')
    expect(driverLabel({ name: 'steel_tumblers', kind: 'object' })).toBe('steel_tumblers')
  })

  it('names a record by the user name, then the file name', () => {
    expect(engagementRecordName({ display_name: 'Spot A', video_filename: 'a.mp4' })).toBe('Spot A')
    expect(engagementRecordName({ display_name: '', video_filename: 'a.mp4' })).toBe('a.mp4')
    expect(engagementRecordName({ video_filename: '' })).toBe('Untitled video')
  })
})
