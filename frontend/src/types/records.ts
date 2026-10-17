import type { UsageMetrics } from './project'

export interface KeyMoment {
  title: string
  description: string
  timestamp_start: string
  timestamp_end: string
  category?: string
  tags?: string[]
  frame_gcs_uri?: string
  frame_signed_url?: string
}

export interface KeyMomentsAnalysis {
  key_moments: KeyMoment[]
  video_summary?: string
}

export interface KeyMomentsRecord {
  id: string
  video_gcs_uri: string
  video_filename: string
  display_name?: string
  video_source: 'upload' | 'production'
  production_id?: string
  mime_type: string
  prompt_id: string
  video_summary?: string
  key_moments: KeyMoment[]
  moment_count: number
  usage: { input_tokens: number; output_tokens: number; model_name: string; cost_usd: number }
  video_signed_url?: string
  createdAt: string
}

export interface ThumbnailScreenshot {
  timestamp: string
  title: string
  description: string
  visual_characteristics: string
  category?: string
  tags?: string[]
  gcs_uri: string
  signed_url?: string
}

export interface ThumbnailRecord {
  id: string
  video_gcs_uri: string
  video_filename: string
  display_name?: string
  video_source: 'upload' | 'production'
  production_id?: string
  mime_type: string
  analysis_prompt_id: string
  collage_prompt_id: string
  video_summary?: string
  screenshots: ThumbnailScreenshot[]
  thumbnail_gcs_uri?: string
  thumbnail_signed_url?: string
  video_signed_url?: string
  status: 'analyzing' | 'screenshots_ready' | 'generating' | 'completed'
  archived: boolean
  createdAt: string
}

export interface CompressedVariant {
  resolution: string
  gcs_uri: string
  job_name: string
  status: 'pending' | 'processing' | 'succeeded' | 'failed'
  signed_url?: string
  child_upload_id?: string
}

export interface UploadRecord {
  id: string
  filename: string
  display_name?: string
  mime_type: string
  file_type: 'video' | 'image' | 'other'
  gcs_uri: string
  file_size_bytes: number
  status?: 'pending' | 'completed' | 'failed'
  compressed_variants: CompressedVariant[]
  parent_upload_id?: string
  resolution_label?: string
  signed_url?: string
  archived: boolean
  createdAt: string
}

export interface CompletedProductionSource {
  id: string
  name: string
  type: string
  final_video_url: string
  video_signed_url: string
  createdAt: string
}

export interface AdaptVariant {
  aspect_ratio: string
  status: 'pending' | 'generating' | 'completed' | 'failed'
  output_gcs_uri?: string
  output_signed_url?: string
  prompt_text_used?: string
  error_message?: string
}

export interface AdaptRecord {
  id: string
  source_gcs_uri: string
  source_filename: string
  source_mime_type: string
  display_name: string
  template_gcs_uri?: string
  preset_bundle: string
  variants: AdaptVariant[]
  status: string
  error_message?: string
  progress_pct: number
  usage: UsageMetrics
  source_signed_url?: string
  template_signed_url?: string
  archived: boolean
  createdAt: string
  completedAt?: string
}

export interface PresetBundle {
  name: string
  ratios: string[]
}

export type SelectCategory =
  | 'directorStyle'
  | 'cameraMovement'
  | 'mood'
  | 'location'
  | 'characterAppearance'

export interface CustomOption {
  id: string
  name: string
  prompt: string
  category: SelectCategory
  createdAt: number
}

export const DEFAULT_OPTIONS: Record<SelectCategory, string[]> = {
  directorStyle: [
    'Christopher Nolan',
    'Wes Anderson',
    'Denis Villeneuve',
    'Greta Gerwig',
    'Ridley Scott',
    'Sofia Coppola',
  ],
  cameraMovement: [
    'Static',
    'Pan Left',
    'Pan Right',
    'Dolly In',
    'Dolly Out',
    'Tracking Shot',
    'Crane Up',
    'Crane Down',
    'Handheld',
    'Steadicam',
  ],
  mood: [
    'Cinematic',
    'Energetic',
    'Calm',
    'Dramatic',
    'Playful',
    'Mysterious',
    'Nostalgic',
    'Futuristic',
  ],
  location: [
    'Studio',
    'Urban Street',
    'Nature',
    'Beach',
    'Mountain',
    'Desert',
    'Indoor Modern',
    'Rooftop',
  ],
  characterAppearance: [
    'Professional attire',
    'Casual streetwear',
    'Formal evening wear',
    'Athletic outfit',
    'Vintage retro style',
  ],
}

export const VIDEO_LENGTH_OPTIONS = ['16', '24', '32', '48', 'custom'] as const

export const SELECT_LABELS: Record<SelectCategory, string> = {
  directorStyle: 'Director Style',
  cameraMovement: 'Camera Movement',
  mood: 'Mood',
  location: 'Location',
  characterAppearance: 'Character Appearance',
}
