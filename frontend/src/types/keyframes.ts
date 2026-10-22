/** S8_KEYFRAMES wire types — mirror `productions_service/services/keyframes_contract.py` 1:1. */
export type KeyframeFrameStatus = 'approved' | 'needs_review' | 'manual_edit'
export type KeyframeSetStatus = 'active' | 'superseded'
export type KeyframeEditor = 'pipeline' | 'human'

/** Max length of a human edit instruction (backend `RegenerateKeyframePayload.instruction`). */
export const KEYFRAME_INSTRUCTION_MAX = 600

export interface KeyframeFrameView {
  t: number
  asset_id: string
  /** Signed (or gs://) URL of the PNG. */
  url: string
  status: KeyframeFrameStatus
  attempts: number
  issues: string[]
  /** `"<shot_id>@t<N>"` when this frame is the previous clip's (shared) last frame. */
  shared_from: string | null
  edited_by: KeyframeEditor
  /** Graph state at t: who does what / holds what. */
  state_summary: string
}

export interface KeyframeSetVersionView {
  set_id: string
  version: number
  status: KeyframeSetStatus
  created_at: string
  reason: string
}

export interface KeyframeStripResponse {
  shot_id: string
  scene_id: string
  clip_index: number
  set_id: string | null
  version: number
  plan_hash: string
  needs_manual_edit: boolean
  /** Graph changed since this set was derived. */
  stale: boolean
  frames: KeyframeFrameView[]
  versions: KeyframeSetVersionView[]
}

export interface KeyframeBoardResponse {
  project_id: string
  /** Active `video.render_strategy`. */
  strategy: string
  shots: KeyframeStripResponse[]
}

export interface RegenerateKeyframePayload {
  instruction?: string
}
