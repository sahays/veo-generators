// Scene Analysis + Engagement contract. Mirrors api/models/domains/models_insights.py
// and the timeline.json / report.json documents written by the worker, 1:1.

export type InsightSourceType = 'upload' | 'production'

export interface InsightUsage {
  input_tokens: number
  output_tokens: number
  model_name: string
  cost_usd: number
}

// ── Timeline (scene analysis output) ────────────────────────────────

export type CueKind = 'dialogue' | 'narration' | 'music' | 'sfx' | 'silence'
export type CueSentiment = 'positive' | 'neutral' | 'negative'
export type EntityKind = 'character' | 'object' | 'location'

export interface TimeRange {
  start_sec: number
  end_sec: number
}

export interface TimelineSegment extends TimeRange {
  id: string
  title: string
  synopsis: string
  location?: string
}

export interface TimelineCue extends TimeRange {
  id: string
  speaker?: string
  text: string
  kind: CueKind
  sentiment?: CueSentiment
}

export interface TimelineEntity {
  id: string
  name: string
  kind: EntityKind
  description?: string
  appearances: TimeRange[]
  screen_time_sec: number
}

export interface TimelineEvent extends TimeRange {
  id: string
  tag: string
  description?: string
  intensity?: number
}

export interface TimelineEmotion extends TimeRange {
  id: string
  emotion: string
  intensity: number
}

export interface TimelineKeyMoment {
  id: string
  start_sec: number
  type: string
  label: string
}

export interface TimelineBeat extends TimeRange {
  id: string
  beat: string
  label?: string
}

export type AdPlacementType =
  | 'mid_roll_break'
  | 'virtual_placement'
  | 'contextual_overlay'
  | 'product_integration'
  | 'sponsored_moment'

export interface TimelineAdOpportunity extends TimeRange {
  id: string
  placement_type: AdPlacementType | string
  surface_or_trigger?: string
  suggested_category: string
  rationale: string
  suitability?: number
}

export interface TimelineDoc {
  schema_version: string
  duration_sec: number
  summary: string
  content_title: string
  cuts: number[]
  segments: TimelineSegment[]
  cues: TimelineCue[]
  entities: TimelineEntity[]
  events: TimelineEvent[]
  emotions: TimelineEmotion[]
  key_moments: TimelineKeyMoment[]
  narrative_beats: TimelineBeat[]
  ad_opportunities?: TimelineAdOpportunity[]
}

export interface FilmstripSpec {
  tile_width: number
  tile_height: number
  columns: number
  rows: number
  interval_sec: number
  count: number
}

export interface FilmstripInfo extends FilmstripSpec {
  url: string
}

export interface TimelineResponse {
  timeline: TimelineDoc
  filmstrip: FilmstripInfo | null
}

export type SceneAnalysisStatus = 'pending' | 'analyzing' | 'processing' | 'completed' | 'failed'

export interface SceneAnalysisRecord {
  id: string
  source_type: InsightSourceType
  source_id: string
  video_gcs_uri: string
  video_filename: string
  display_name?: string
  mime_type: string
  focus: string
  model_id?: string | null
  region?: string | null
  status: SceneAnalysisStatus
  stage: string
  stage_detail: string
  progress_pct: number
  error_message?: string | null
  duration_sec: number
  window_count: number
  summary: string
  content_title: string
  counts: Record<string, number>
  filmstrip?: FilmstripSpec | null
  schema_version: string
  usage: InsightUsage
  video_signed_url?: string
  archived?: boolean
  createdAt: string
  completedAt?: string | null
}

export interface SceneAnalysisCreate {
  source_type: InsightSourceType
  source_id: string
  focus?: string
  display_name?: string
  model_id?: string
  region?: string
}

// ── Engagement ──────────────────────────────────────────────────────

export type EngagementSignalKind = 'template' | 'barc'

export interface EngagementSignalSpec {
  kind: EngagementSignalKind
  template_id?: string | null
  upload_id?: string | null
  csv_filename?: string
  time_column?: string | null
  metric?: string | null
  offset_sec?: number
}

export interface EngagementTemplate {
  id: string
  label: string
  description: string
  preview: number[] // ~40 values in 0..100, evenly spaced over the video
}

export interface SignalPreview {
  filename: string
  row_count: number
  columns: string[]
  time_column: string | null
  metrics: string[]
  primary_metric: string | null
  duration_sec: number
  interval_sec: number
  sample_rows: Record<string, string>[]
  warnings: string[]
}

export type SignalPoint = [number, number] // [t_sec, value]; value holds for [t, t + interval)

export interface ReportMetric {
  key: string
  label: string
  primary: boolean
  points: SignalPoint[]
}

export interface ReportSignalMeta {
  kind: EngagementSignalKind
  template_id?: string | null
  label: string
  simulated: boolean // true for templates: illustrative data, not measured
  primary_metric: string
  unit: string
  offset_sec: number
  point_count: number
  interval_sec: number
}

export interface ReportStats {
  avg: number
  median: number
  p75: number
  min: number
  max: number
  std: number
}

export type ExtremumKind = 'peak' | 'valley' | 'drop'

export interface ReportExtremum {
  id: string
  kind: ExtremumKind
  time_sec: number
  value: number
  prominence: number
  delta_pct: number // vs overall average
  window: TimeRange
  segment_id: string | null
  title: string
  explanation: string
  drivers: string[]
}

export interface ReportSegmentStat {
  segment_id: string
  avg: number
  delta_pct: number
  rank: number // 1 = highest average
}

export type InfluenceKind = EntityKind | 'emotion' | 'event'

export interface ReportInfluence {
  key: string // e.g. "character:asha"
  ref_id: string | null // timeline entity id when kind is an entity kind
  name: string
  kind: InfluenceKind
  avg_during: number
  delta_pct: number
  coverage_sec: number
  coverage_pct: number
  low_support: boolean
  ranges: TimeRange[]
}

export interface RecommendationEvidence {
  key: string
  name: string
  kind: string
  delta_pct: number
  coverage_sec: number
  anchor_times: number[]
}

export interface ReportRecommendation {
  title: string
  rationale: string
  expected_lift: 'low' | 'medium' | 'high'
  evidence: RecommendationEvidence | null
}

export interface ReportSegmentFix extends TimeRange {
  segment_id: string
  avg: number
  what_happened: string
  why_low: string
  fix: string
}

export interface ReportRecommendations {
  headline: string
  do_more: ReportRecommendation[]
  do_less: ReportRecommendation[]
  segment_fixes: ReportSegmentFix[]
}

export interface ReportKpis {
  avg: number
  peak: { time_sec: number; value: number } | null
  low: { time_sec: number; value: number } | null
  biggest_drop: { time_sec: number; delta: number } | null
  hook_avg: number | null // average over the opening of the video
}

export interface EngagementReport {
  schema_version: string
  duration_sec: number
  signal: ReportSignalMeta
  metrics: ReportMetric[]
  smoothed: SignalPoint[]
  stats: ReportStats
  extrema: ReportExtremum[]
  segments: ReportSegmentStat[]
  influence: ReportInfluence[]
  recommendations: ReportRecommendations
  kpis: ReportKpis
}

export type EngagementStatus = 'pending' | 'processing' | 'completed' | 'failed'

export interface EngagementRecord {
  id: string
  scene_analysis_id: string
  source_type: InsightSourceType
  source_id: string
  video_gcs_uri: string
  video_filename: string
  display_name?: string
  mime_type: string
  signal: EngagementSignalSpec
  status: EngagementStatus
  stage: string
  stage_detail: string
  progress_pct: number
  error_message?: string | null
  duration_sec: number
  headline: string
  kpis: Partial<ReportKpis>
  schema_version: string
  usage: InsightUsage
  video_signed_url?: string
  archived?: boolean
  createdAt: string
  completedAt?: string | null
}

export interface EngagementCreate {
  scene_analysis_id?: string
  source_type?: InsightSourceType
  source_id?: string
  signal: EngagementSignalSpec
  display_name?: string
  model_id?: string
  region?: string
}

export interface EngagementCreateResponse {
  id: string
  status: EngagementStatus
  scene_analysis_id: string
}
