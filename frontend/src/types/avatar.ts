export type AvatarStyle =
  | 'talkative'
  | 'funny'
  | 'serious'
  | 'cynical'
  | 'to_the_point'

export type AvatarVersion = 'v1' | 'v2'

// Full set of Gemini Live prebuilt voices (see ffeldhaus/live-agent
// constants.ts → VOICE_PRESETS). Backend AvatarVoice enum mirrors this.
export type AvatarVoice =
  | 'Kore' | 'Puck' | 'Charon' | 'Fenrir' | 'Aoede' | 'Leda' | 'Orus' | 'Zephyr'
  | 'Autonoe' | 'Umbriel' | 'Erinome' | 'Laomedeia' | 'Schedar' | 'Achird'
  | 'Sadachbia' | 'Enceladus' | 'Algieba' | 'Algenib' | 'Achernar' | 'Gacrux'
  | 'Zubenelgenubi' | 'Sadaltager' | 'Callirrhoe' | 'Iapetus' | 'Despina'
  | 'Rasalgethi' | 'Alnilam' | 'Pulcherrima' | 'Vindemiatrix' | 'Sulafat'

export type Gender = 'female' | 'male'

export interface AvatarVoiceInfo {
  id: AvatarVoice
  description: string
  gender: Gender
}

// Voice descriptions come straight from the upstream catalog; gender labels
// are best-effort based on common name conventions and our own A/B testing
// (Charon → male, Aoede → female, etc.). Used for filtering only.
export const VOICE_CATALOG: AvatarVoiceInfo[] = [
  { id: 'Kore', description: 'Firm', gender: 'female' },
  { id: 'Aoede', description: 'Breezy', gender: 'female' },
  { id: 'Leda', description: 'Youthful', gender: 'female' },
  { id: 'Callirrhoe', description: 'Easy-going', gender: 'female' },
  { id: 'Despina', description: 'Smooth', gender: 'female' },
  { id: 'Erinome', description: 'Clear', gender: 'female' },
  { id: 'Achernar', description: 'Soft', gender: 'female' },
  { id: 'Pulcherrima', description: 'Forward', gender: 'female' },
  { id: 'Vindemiatrix', description: 'Gentle', gender: 'female' },
  { id: 'Sulafat', description: 'Warm', gender: 'female' },
  { id: 'Autonoe', description: 'Bright', gender: 'female' },
  { id: 'Laomedeia', description: 'Upbeat', gender: 'female' },
  { id: 'Sadachbia', description: 'Lively', gender: 'female' },
  { id: 'Charon', description: 'Informative', gender: 'male' },
  { id: 'Fenrir', description: 'Excitable', gender: 'male' },
  { id: 'Orus', description: 'Firm', gender: 'male' },
  { id: 'Puck', description: 'Upbeat', gender: 'male' },
  { id: 'Schedar', description: 'Even', gender: 'male' },
  { id: 'Achird', description: 'Friendly', gender: 'male' },
  { id: 'Algenib', description: 'Gravelly', gender: 'male' },
  { id: 'Enceladus', description: 'Breathy', gender: 'male' },
  { id: 'Iapetus', description: 'Clear', gender: 'male' },
  { id: 'Rasalgethi', description: 'Informative', gender: 'male' },
  { id: 'Alnilam', description: 'Firm', gender: 'male' },
  { id: 'Algieba', description: 'Smooth', gender: 'male' },
  { id: 'Sadaltager', description: 'Knowledgeable', gender: 'male' },
  { id: 'Umbriel', description: 'Easy-going', gender: 'male' },
  { id: 'Zubenelgenubi', description: 'Casual', gender: 'male' },
  { id: 'Zephyr', description: 'Bright', gender: 'male' },
  { id: 'Gacrux', description: 'Mature', gender: 'male' },
]

// 12 preset avatars from upstream. Images are bundled at /avatars/<id>.png.
// See ffeldhaus/live-agent constants.ts → AVATAR_PRESETS.
export interface AvatarPresetInfo {
  id: string // matches Gemini Live's avatarConfig.avatarName
  displayName: string
  mood: string
  defaultGreeting: string
  imageUrl: string // public path
  gender: Gender
}

export const PRESET_CATALOG: AvatarPresetInfo[] = [
  { id: 'Hana', displayName: 'Hana', mood: 'Studious, calm, disciplined',
    defaultGreeting: 'Hello. I am ready to assist you with your queries.',
    imageUrl: '/avatars/hana.png', gender: 'female' },
  { id: 'Carmen', displayName: 'Carmen', mood: 'Wise, nurturing, academic',
    defaultGreeting: 'Welcome. What knowledge shall we seek today?',
    imageUrl: '/avatars/carmen.png', gender: 'female' },
  { id: 'Ingrid', displayName: 'Ingrid', mood: 'Formal, authoritative, precise',
    defaultGreeting: 'Good day. Please state your inquiry.',
    imageUrl: '/avatars/ingrid.png', gender: 'female' },
  { id: 'Kira', displayName: 'Kira', mood: 'Practical, grounded, industrious',
    defaultGreeting: "Hello. Let's get to work. How can I help?",
    imageUrl: '/avatars/kira.png', gender: 'female' },
  { id: 'Piper', displayName: 'Piper', mood: 'Artistic, vibrant, soulful',
    defaultGreeting: 'Hello! Excited to explore new ideas with you.',
    imageUrl: '/avatars/piper.png', gender: 'female' },
  { id: 'Vera', displayName: 'Vera', mood: 'Elegant, sophisticated, musical',
    defaultGreeting: 'Good day. It is a pleasure to assist you.',
    imageUrl: '/avatars/vera.png', gender: 'female' },
  { id: 'Ben', displayName: 'Ben', mood: 'Friendly, modern, approachable',
    defaultGreeting: 'Hey there! Great to meet you. How can I help?',
    imageUrl: '/avatars/ben.png', gender: 'male' },
  { id: 'Jay', displayName: 'Jay', mood: 'Executive, reliable, corporate',
    defaultGreeting: "Hello. Let's get down to business. What do you need?",
    imageUrl: '/avatars/jay.png', gender: 'male' },
  { id: 'Kai', displayName: 'Kai', mood: 'Breezy, youthful, optimistic',
    defaultGreeting: "Hi! Awesome day, isn't it? What's up?",
    imageUrl: '/avatars/kai.png', gender: 'male' },
  { id: 'Leo', displayName: 'Leo', mood: 'Creative, artisanal, vintage',
    defaultGreeting: "Hey! Let's create something amazing today!",
    imageUrl: '/avatars/leo.png', gender: 'male' },
  { id: 'Paul', displayName: 'Paul', mood: 'Traditional, senior, dignified',
    defaultGreeting: 'Greetings. How may I be of service?',
    imageUrl: '/avatars/paul.png', gender: 'male' },
  { id: 'Sam', displayName: 'Sam', mood: 'Intellectual, smart-casual, cozy',
    defaultGreeting: 'Hi. Looking forward to a thoughtful conversation.',
    imageUrl: '/avatars/sam.png', gender: 'male' },
]

export interface Avatar {
  id: string
  name: string
  image_gcs_uri: string
  image_signed_url?: string
  style: AvatarStyle
  persona_prompt: string
  is_default: boolean
  archived: boolean
  createdAt: string
  version: AvatarVersion
  voice?: AvatarVoice | null
  preset_name?: string | null
  language?: string
  default_greeting?: string
  enable_grounding?: boolean
}

// BCP-47 language codes Gemini Live officially supports. Names are the
// presentation labels.
export const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
  { value: 'en-US', label: 'English (United States)' },
  { value: 'en-GB', label: 'English (United Kingdom)' },
  { value: 'en-IN', label: 'English (India)' },
  { value: 'en-AU', label: 'English (Australia)' },
  { value: 'es-US', label: 'Spanish (United States)' },
  { value: 'es-ES', label: 'Spanish (Spain)' },
  { value: 'fr-FR', label: 'French (France)' },
  { value: 'de-DE', label: 'German (Germany)' },
  { value: 'it-IT', label: 'Italian' },
  { value: 'pt-BR', label: 'Portuguese (Brazil)' },
  { value: 'hi-IN', label: 'Hindi (India)' },
  { value: 'ja-JP', label: 'Japanese' },
  { value: 'ko-KR', label: 'Korean' },
  { value: 'zh-CN', label: 'Chinese (Simplified)' },
  { value: 'nl-NL', label: 'Dutch' },
  { value: 'pl-PL', label: 'Polish' },
  { value: 'tr-TR', label: 'Turkish' },
  { value: 'ar-XA', label: 'Arabic (Generic)' },
]

export type AvatarTurnStatus = 'pending' | 'generating' | 'completed' | 'failed'

export interface AvatarTurn {
  id: string
  avatar_id: string
  question: string
  answer_text: string
  video_gcs_uri?: string
  video_signed_url?: string
  status: AvatarTurnStatus
  progress_pct: number
  error_message?: string
  model_id?: string
  region?: string
  createdAt: string
  completedAt?: string
}

export interface AskAvatarResponse {
  turn_id: string
  answer_text: string
  status: AvatarTurnStatus
}

export interface AvatarLiveConfig {
  voice: AvatarVoice
  language: string
  system_instruction: string
  custom_avatar_url: string
  default_greeting: string | null
}

export const STYLE_LABELS: Record<AvatarStyle, string> = {
  talkative: 'Talkative',
  funny: 'Funny',
  serious: 'Serious',
  cynical: 'Cynical',
  to_the_point: 'To the point',
}

// Marker the backend stores in turn.question for voice turns. The frontend
// renders a mic icon instead of a text bubble for these turns since browser
// transcription is unreliable and we no longer surface a transcript.
export const VOICE_TURN_MARKER = '__voice__'
