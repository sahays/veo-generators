import { getInviteCode, type JsonValue } from './api/core/_http'
import { auth } from './api/core/auth'
import { diagnostics } from './api/core/diagnostics'
import { models } from './api/core/models'
import { pricing } from './api/core/pricing'
import { system } from './api/core/system'
import { adapts } from './api/endpoints/adapts'
import { ai } from './api/endpoints/ai'
import { assets, type UploadInitResp, type UploadResp } from './api/endpoints/assets'
import { avatars } from './api/endpoints/avatars'
import {
  chat,
  type SharedChatMessageItem,
  type SharedChatRecord,
} from './api/endpoints/chat'
import {
  dubbing,
  type DubLanguage,
  type DubLanguagesResponse,
} from './api/endpoints/dubbing'
import { keyMoments } from './api/endpoints/keyMoments'
import { projects } from './api/endpoints/projects'
import { promo } from './api/endpoints/promo'
import { reframe } from './api/endpoints/reframe'
import { thumbnails } from './api/endpoints/thumbnails'
import { uploads } from './api/endpoints/uploads'

export type {
  DubLanguage,
  DubLanguagesResponse,
  JsonValue,
  SharedChatMessageItem,
  SharedChatRecord,
  UploadInitResp,
  UploadResp,
}

export interface Project {
  id: string
  name: string
  prompt: string
  refined_prompt?: string
  director_style?: string
  camera_movement?: string
  mood?: string
  location?: string
  character_appearance?: string
  video_length: string
  status: 'draft' | 'generating' | 'completed' | 'failed'
  media_files: JsonValue[]
  storyboard_frames: JsonValue[]
  created_at: string
  updated_at: string
}

export const api = {
  auth,
  projects,
  ai,
  keyMoments,
  thumbnails,
  assets,
  uploads,
  system,
  reframe,
  promo,
  adapts,
  dubbing,
  diagnostics,
  chat,
  models,
  pricing,
  avatars,
}

// Build a wss:// URL for the v2 live session, with the invite code in the
// query string (WebSocket upgrades can't carry custom headers).
export function buildAvatarLiveUrl(avatarId: string): string {
  const inviteCode = getInviteCode()
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const qs = new URLSearchParams({ invite_code: inviteCode }).toString()
  return `${proto}//${host}/api/v1/avatars/${avatarId}/live?${qs}`
}
