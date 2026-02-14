import { z } from 'zod'

export const projectSchema = z.object({
  name: z.string().min(1, 'Project name is required'),
  prompt: z
    .string()
    .min(10, 'Prompt must be at least 10 characters')
    .max(2000, 'Prompt must be under 2000 characters'),
  directorStyle: z.string().optional(),
  cameraMovement: z.string().optional(),
  mood: z.string().optional(),
  location: z.string().optional(),
  characterAppearance: z.string().optional(),
  videoLength: z.enum(['16', '24', '32', '48']),
})

export type ProjectFormData = z.infer<typeof projectSchema>

export type ProjectStatus = 'draft' | 'generating' | 'completed' | 'failed'

export interface Project {
  id: string
  name: string
  prompt: string
  directorStyle?: string
  cameraMovement?: string
  mood?: string
  location?: string
  characterAppearance?: string
  videoLength: '16' | '24' | '32' | '48'
  status: ProjectStatus
  mediaFiles: MediaFile[]
  storyboardFrames: StoryboardFrame[]
  createdAt: number
  updatedAt: number
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

export const VIDEO_LENGTH_OPTIONS = ['16', '24', '32', '48'] as const

export const SELECT_LABELS: Record<SelectCategory, string> = {
  directorStyle: 'Director Style',
  cameraMovement: 'Camera Movement',
  mood: 'Mood',
  location: 'Location',
  characterAppearance: 'Character Appearance',
}
