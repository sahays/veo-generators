import { z } from 'zod'
import type { StoryGraphData } from './storygraph'

export * from './storygraph'
export * from './records'
export * from './productionPresets'

export const sceneSchema = z.object({
  id: z.string(),
  visual_description: z.string().min(10),
  narration: z.string().optional(),
  narration_enabled: z.boolean().optional(),
  music_description: z.string().optional(),
  music_enabled: z.boolean().optional(),
  timestamp_start: z.string(),
  timestamp_end: z.string(),
  metadata: z.object({
    location: z.string().optional(),
    characters: z.array(z.string()).optional(),
    camera_angle: z.string().optional(),
    lighting: z.string().optional(),
    style: z.string().optional(),
    mood: z.string().optional(),
  }).optional(),
  enter_transition: z.string().optional(),
  exit_transition: z.string().optional(),
  music_transition: z.string().optional(),
  thumbnail_url: z.string().optional(),
  end_frame_url: z.string().optional(),
  video_url: z.string().optional(),
  generated_prompt: z.string().optional(),
  image_prompt: z.string().optional(),
  end_frame_prompt: z.string().optional(),
  video_prompt: z.string().optional(),
  operation_name: z.string().optional(),
  status: z.string().optional(),
  error_message: z.string().optional(),
  speaker_notes: z.string().optional(),
  video_resolution: z.string().optional(),
  eval_status: z.string().optional(),
  eval_feedback: z.string().optional(),
  regen_count: z.number().optional(),
  tokens_consumed: z.object({
    input: z.number().default(0),
    output: z.number().default(0),
  }).optional(),
})

export type RenderQuality = 'draft' | 'final'
export type VideoResolution = '360p' | '720p' | '1080p'

export type Scene = z.infer<typeof sceneSchema> & {
  video_resolution?: VideoResolution | string
  eval_status?: 'passed' | 'flagged' | 'regenerating' | 'regenerated' | string
}

export type ProjectType = 'movie' | 'advertizement' | 'social'
export type ProductionLanguage = 'en-IN' | 'hi-IN' | 'en-US'

export const PRODUCTION_LANGUAGES: {
  id: ProductionLanguage
  label: string
  sub: string
}[] = [
  { id: 'en-IN', label: 'English (India)', sub: 'Indian English audio & video' },
  { id: 'hi-IN', label: 'Hindi (हिन्दी)', sub: 'Native Hindi audio & video' },
  { id: 'en-US', label: 'English (US)', sub: 'Standard US English' },
]

export const projectSchema = z.object({
  name: z.string().min(1, 'Project name is required'),
  type: z.enum(['movie', 'advertizement', 'social']),
  base_concept: z.string().min(10, 'Concept must be at least 10 characters').max(10000),
  video_length: z.string().min(1),
  orientation: z.enum(['16:9', '9:16']),
  language: z.enum(['en-IN', 'hi-IN', 'en-US']),
  visual_style_preset: z.string().optional(),
  color_palette_preset: z.string().optional(),
  director_style_preset: z.string().optional(),
  screenplay_style_preset: z.string().optional(),
  music_style_preset: z.string().optional(),
  auto_approve_gates: z.boolean().optional(),
  reference_image_url: z.string().optional(),
  prompt_id: z.string().optional(),
  schema_id: z.string().optional(),
})

export type ProjectFormData = z.infer<typeof projectSchema> & {
  prompt_id?: string
  schema_id?: string
  auto_approve_gates?: boolean
}

export type ProjectStatus =
  | 'draft'
  | 'analyzing'
  | 'scripted'
  | 'reviewing'
  | 'generating'
  | 'stitching'
  | 'evaluating'
  | 'regenerating'
  | 'running'
  | 'awaiting_g1'
  | 'awaiting_g2'
  | 'awaiting_g3'
  | 'completed'
  | 'completed_partial'
  | 'needs_review'
  | 'failed'

export interface SystemResourceInfo {
  id: string
  name: string
  version: number
}

export interface SystemResource {
  id: string
  type: 'prompt' | 'schema'
  category: string
  name: string
  version: number
  content: string
  is_active: boolean
  createdAt: string
}

export interface UsageMetrics {
  input_tokens: number
  output_tokens: number
  model_name: string
  cost_usd: number
  image_generations: number
  image_input_tokens?: number
  image_output_tokens?: number
  image_cost_usd: number
  veo_videos: number
  veo_seconds: number
  veo_unit_cost: number
  veo_cost_usd: number
  transcoder_minutes?: number
  transcoder_cost_usd?: number
  diarization_minutes?: number
  diarization_cost_usd?: number
}

export interface ServiceLineItem {
  id: string
  label: string
  unit: 'token' | 'image' | 'second' | 'minute'
  units: number
  unit_cost_usd: number
  subtotal_usd: number
}

export interface FeaturePricing {
  feature: string
  services: ServiceLineItem[]
  total_usd: number
  confidence?: 'high' | 'medium' | 'low'
  notes?: string
}

export type FeatureId = 'production' | 'adapts' | 'reframe' | 'promo' | 'key_moments' | 'thumbnails'

export interface PricingRatesResponse {
  text_models: Record<string, {
    label: string
    tiers: { threshold_tokens: number | null; input_per_token: number; output_per_token: number }[]
  }>
  image_models: Record<string, {
    label: string
    input_per_token: number
    output_per_token: number
  }>
  video_models: Record<string, { label: string; per_second: number }>
  flat_services: Record<string, { label: string; unit: string; unit_cost_usd: number }>
}

export interface PricingFeaturesResponse {
  features: Record<FeatureId, { services: { id: string; label: string; unit: string; unit_cost_usd: number }[] }>
}

export interface PricingEstimateRequest {
  feature: FeatureId
  source_duration_seconds?: number
  video_length_seconds?: number
  scene_count?: number
  video_model?: string
  text_model?: string
  image_model?: string
  variant_count?: number
  segment_count?: number
  has_title_card?: boolean
  thumbnail_count?: number
}

export interface MediaFile {
  id: string
  file: File
  previewUrl: string
  type: 'image' | 'video'
}

export interface StoryboardFrame {
  id: string
  imageUrl: string
  caption: string
  timestamp: string
}

export interface GlobalStyle {
  look: string
  mood: string
  color_grading: string
  lighting_style: string
  soundtrack_style?: string
}

export interface CharacterProfile {
  id: string
  description: string
  wardrobe?: string
}

export interface Continuity {
  characters: CharacterProfile[]
  setting_notes?: string
}

export interface PipelineStepLog {
  step_id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed'
  detail?: string
  usage?: UsageMetrics
  started_at?: string
  completed_at?: string
}

export interface StoryboardReviewIssue {
  scene_number: number
  category: string
  severity: 'critical' | 'warning' | string
  problem: string
  fix_applied: string
}

export interface StoryboardReviewReport {
  overall_score: number
  summary: string
  issues: StoryboardReviewIssue[]
  usage?: UsageMetrics
  reviewed_at?: string
}

export interface SceneEvalFinding {
  scene_number: number
  scene_id?: string
  category: string
  severity: 'critical' | 'warning' | string
  observed_issue: string
  regenerate_frame: boolean
  regenerate_video: boolean
  corrected_visual_description?: string
  corrected_speaker_notes?: string
  corrected_narration?: string
  corrected_music_description?: string
}

export interface VideoEvalReport {
  overall_score: number
  passed: boolean
  iteration: number
  summary: string
  findings: SceneEvalFinding[]
  regenerated_scene_ids?: string[]
  usage?: UsageMetrics
  evaluated_at?: string
}

export interface Project {
  id: string
  name: string
  type: ProjectType
  base_concept: string
  video_length: string
  orientation: '16:9' | '9:16'
  language?: ProductionLanguage
  visual_style_preset?: string
  color_palette_preset?: string
  director_style_preset?: string
  screenplay_style_preset?: string
  music_style_preset?: string
  auto_approve_gates?: boolean
  current_stage?: string
  blocked_gate?: string | null
  story_graph?: StoryGraphData
  status: ProjectStatus
  error_message?: string | null
  render_quality?: RenderQuality
  video_resolution?: VideoResolution
  draft_video_url?: string
  pipeline_stage?: string
  pipeline_steps?: PipelineStepLog[]
  review_report?: StoryboardReviewReport
  eval_report?: VideoEvalReport
  prompt_info?: SystemResourceInfo
  schema_info?: SystemResourceInfo
  reference_image_url?: string
  global_style?: GlobalStyle
  continuity?: Continuity
  analysis_prompt?: string
  final_video_url?: string
  scenes: Scene[]
  archived?: boolean
  total_usage: UsageMetrics
  createdAt: number
  updatedAt: number
}
