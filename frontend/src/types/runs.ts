/**
 * Async stage-run contract — mirrors `productions_service/services/jobs/contract.py` and
 * `productions_service/storygraph/schemas/stage_job.py` 1:1.
 *
 * Run POSTs answer `202 RunAccepted` immediately; progress is read from the cheap
 * `GET /api/v1/productions/{id}/status` endpoint (`ProductionStatusResponse`).
 */

export type RunKind =
  | 'pipeline'
  | 'stage'
  | 'assemble'
  | 'repair'
  | 'shot_regenerate'
  | 'keyframe_regenerate'
  | 'appearance_regenerate'

export type RunStatus = 'queued' | 'running' | 'completed' | 'paused' | 'failed' | 'interrupted'

export type ProgressUnit = 'clips' | 'frames' | 'shots'

export interface RunProgress {
  done: number
  total: number
  unit: ProgressUnit
  current: string | null
}

export interface RunView {
  run_id: string
  kind: RunKind
  /** Human text, e.g. "Resume keyframes". */
  label: string
  /** Current stage id (S1_EXTRACT..S10_ASSEMBLE, S8_REPAIR). */
  stage: string | null
  /** Planned stage sequence (may be empty). */
  stages: string[]
  status: RunStatus
  /** `null` => indeterminate (authoring stages). */
  progress: RunProgress | null
  /** ISO-8601 UTC timestamps. */
  started_at: string
  heartbeat_at: string
  finished_at: string | null
  error: string | null
  /** e.g. repair: {repair_report, assembled}; keyframe_regenerate: {shot_id, keyframe_set_id}. */
  result: Record<string, unknown> | null
}

export interface RunAccepted {
  accepted: true
  stage_run_id: string
  run: RunView
}

export interface ProductionStatusResponse {
  project_id: string
  pipeline_status: string
  current_stage: string | null
  /** ONLY queued/running. Non-null => a run is live => disable conflicting actions. */
  active_run: RunView | null
  /** Most recent finished run: completed | paused | failed | interrupted. */
  last_run: RunView | null
  last_error: string | null
  /** Use for clock-skew-safe elapsed time. */
  server_time: string
}
