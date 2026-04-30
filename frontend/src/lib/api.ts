import { adapts } from './api/adapts'
import { ai } from './api/ai'
import { assets } from './api/assets'
import { auth } from './api/auth'
import { avatars } from './api/avatars'
import { chat } from './api/chat'
import { diagnostics } from './api/diagnostics'
import { getInviteCode } from './api/_http'
import { keyMoments } from './api/keyMoments'
import { models } from './api/models'
import { pricing } from './api/pricing'
import { projects } from './api/projects'
import { promo } from './api/promo'
import { reframe } from './api/reframe'
import { system } from './api/system'
import { thumbnails } from './api/thumbnails'
import { uploads } from './api/uploads'

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
  media_files: any[]
  storyboard_frames: any[]
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
