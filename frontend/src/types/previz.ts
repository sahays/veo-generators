/** Blender previz wire types — mirror the productions-service `/previz` contract 1:1. */
export type PrevizStageStatus = 'idle' | 'running' | 'approved' | 'failed'
export type PrevizJobStatus = 'pending' | 'running' | 'done' | 'failed'
export type PrevizRestyleVariant = 'E1_omni_restyle' | 'E2_keyframe_restyle'
export type PrevizRunVariant = 'previz_only' | PrevizRestyleVariant | 'both'

export interface PrevizStageRun {
  status: PrevizStageStatus
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface PrevizLayout {
  location_id: string
  name: string
  version: number
  thumbnail_url: string | null
}

export interface PrevizVariant {
  variant: PrevizRestyleVariant
  status: PrevizJobStatus
  video_url: string | null
  frame_urls: string[]
  failure_reason: string | null
  promoted: boolean
}

export interface ShotPreviz {
  shot_id: string
  scene_id: string
  clip_index: number
  status: PrevizJobStatus
  failure_reason: string | null
  previz_video_url: string | null
  render_seconds: number | null
  variants: PrevizVariant[]
}

export interface PrevizBoardResponse {
  project_id: string
  blender_version: string | null
  stage_run: PrevizStageRun | null
  layouts: PrevizLayout[]
  shots: ShotPreviz[]
}

export interface PrevizRunPayload {
  variant: PrevizRunVariant
  /** `null` = every scene. */
  scene_ids: string[] | null
  force: boolean
}

export interface PrevizRunAccepted {
  accepted: true
  stage_run_id: string
}

export interface PrevizPromotePayload {
  variant: PrevizRestyleVariant
}
