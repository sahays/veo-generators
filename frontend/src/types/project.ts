import { z } from 'zod'

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
  thumbnail_url: z.string().optional(),
  video_url: z.string().optional(),
  generated_prompt: z.string().optional(),
  image_prompt: z.string().optional(),
  video_prompt: z.string().optional(),
  operation_name: z.string().optional(),
  status: z.string().optional(),
  error_message: z.string().optional(),
  tokens_consumed: z.object({
    input: z.number().default(0),
    output: z.number().default(0),
  }).optional(),
})

export type Scene = z.infer<typeof sceneSchema>

export type ProjectType = 'movie' | 'advertizement' | 'social'

export const projectSchema = z.object({
  name: z.string().min(1, 'Project name is required'),
  type: z.enum(['movie', 'advertizement', 'social']),
  base_concept: z.string().min(10, 'Concept must be at least 10 characters').max(2000),
  video_length: z.enum(['16', '24', '32', '48', 'custom']),
  orientation: z.enum(['16:9', '9:16']),
  reference_image_url: z.string().optional(),
  prompt_id: z.string().optional(),
  schema_id: z.string().optional(),
})

export type ProjectFormData = z.infer<typeof projectSchema> & {
  prompt_id?: string
  schema_id?: string
}

export type ProjectStatus = 'draft' | 'analyzing' | 'scripted' | 'generating' | 'stitching' | 'completed' | 'failed'

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
  total_input_tokens: number
  total_output_tokens: number
  estimated_cost_usd: number
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

export interface CustomOption {
  id: string
  name: string
  prompt: string
  category: SelectCategory
  createdAt: number
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

export interface Project {
  id: string
  name: string
  type: ProjectType
  base_concept: string
  video_length: '16' | '24' | '32' | '48' | 'custom'
  orientation: '16:9' | '9:16'
  status: ProjectStatus
  prompt_info?: SystemResourceInfo
  schema_info?: SystemResourceInfo
  reference_image_url?: string
  global_style?: GlobalStyle
  continuity?: Continuity
  analysis_prompt?: string
  final_video_url?: string
  scenes: Scene[]
  archived?: boolean
  usage: UsageMetrics
  createdAt: number
  updatedAt: number
}

export interface KeyMoment {
  title: string
  description: string
  timestamp_start: string
  timestamp_end: string
  category?: string
  tags?: string[]
}

export interface KeyMomentsAnalysis {
  key_moments: KeyMoment[]
  video_summary?: string
}

export interface KeyMomentsRecord {
  id: string
  video_gcs_uri: string
  video_filename: string
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

export interface CompletedProductionSource {
  id: string
  name: string
  type: string
  final_video_url: string
  video_signed_url: string
  createdAt: string
}

export type SelectCategory =
  | 'directorStyle'
  | 'cameraMovement'
  | 'mood'
  | 'location'
  | 'characterAppearance'

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
