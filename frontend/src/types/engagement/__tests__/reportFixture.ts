import type { EngagementReport, ReportExtremum, ReportInfluence, SignalPoint } from '@/types/insights'

/**
 * A small hand-built report for the unit tests: 9 five-second samples over
 * the 45 s ad-spot fixture, two metrics on very different scales, and a
 * smoothed series that differs from the raw one.
 */
const INDEX_POINTS: SignalPoint[] = [[0, 40], [5, 30], [10, 50], [15, 60], [20, 70], [25, 65], [30, 90], [35, 55], [40, 20]]
const REACH_POINTS: SignalPoint[] = INDEX_POINTS.map(([time, value]) => [time, value * 100 + 1000])
const SMOOTHED: SignalPoint[] = [[0, 35], [5, 40], [10, 46.67], [15, 60], [20, 65], [25, 75], [30, 70], [35, 55], [40, 37.5]]

function extremum(id: string, kind: ReportExtremum['kind'], time: number, value: number): ReportExtremum {
  return {
    id,
    kind,
    time_sec: time,
    value,
    prominence: 10,
    delta_pct: Math.round(((value - 53.33) / 53.33) * 10000) / 100,
    window: { start_sec: Math.max(time - 5, 0), end_sec: Math.min(time + 10, 45) },
    segment_id: 'seg-7',
    title: '',
    explanation: '',
    drivers: [],
  }
}

function influence(key: string, kind: ReportInfluence['kind'], delta: number, lowSupport = false): ReportInfluence {
  return {
    key,
    ref_id: null,
    name: key.split(':')[1],
    kind,
    avg_during: 53.33 * (1 + delta / 100),
    delta_pct: delta,
    coverage_sec: lowSupport ? 2 : 20,
    coverage_pct: lowSupport ? 4.44 : 44.44,
    low_support: lowSupport,
    ranges: [{ start_sec: 10, end_sec: 20 }, { start_sec: 30, end_sec: 40 }],
  }
}

export const SMALL_REPORT: EngagementReport = {
  schema_version: 'engagement-report-v1',
  duration_sec: 45,
  signal: { kind: 'barc', template_id: null, label: 'ratings.csv', simulated: false, primary_metric: 'Index', unit: '', offset_sec: 0, point_count: 9, interval_sec: 5 },
  metrics: [
    { key: 'index', label: 'Index', primary: true, points: INDEX_POINTS },
    { key: 'reach', label: 'Reach', primary: false, points: REACH_POINTS },
  ],
  smoothed: SMOOTHED,
  stats: { avg: 53.33, median: 55, p75: 65, min: 20, max: 90, std: 20 },
  // Report order: peaks, valleys, drops. Not time order.
  extrema: [extremum('peak-1', 'peak', 30, 70), extremum('valley-1', 'valley', 5, 40), extremum('drop-1', 'drop', 35, 55)],
  segments: [{ segment_id: 'seg-1', avg: 40, delta_pct: -25, rank: 2 }, { segment_id: 'seg-7', avg: 80, delta_pct: 50, rank: 1 }],
  influence: [
    influence('event:comedy', 'event', 30),
    influence('character:asha', 'character', 12),
    influence('emotion:calm', 'emotion', -18),
    influence('character:mr. rao', 'character', 8, true),
  ],
  recommendations: { headline: '', do_more: [], do_less: [], segment_fixes: [] },
  kpis: { avg: 53.33, peak: { time_sec: 30, value: 90 }, low: { time_sec: 40, value: 20 }, biggest_drop: { time_sec: 35, delta: -35 }, hook_avg: 40 },
}
