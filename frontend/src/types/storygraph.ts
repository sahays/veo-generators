export interface StoryGraphStyleGuide {
  id?: string
  visual_medium?: string
  visual_style_preset?: string
  color_palette_preset?: string
  director_style_preset?: string
  screenplay_style_preset?: string
  music_style_preset?: string
  lens_language?: string
  lighting_rules?: string
  palette?: string[]
  continuity_rules?: string
  character_consistency_rules?: string
  scene_consistency_rules?: string
}

export interface StoryGraphAttributeValue {
  value?: string | number | boolean | null
  provenance?: string
}

export interface StoryGraphEntity {
  id: string
  entity_type?: string
  canonical_name: string
  status?: string
  aliases?: string[]
  attributes?: Record<string, StoryGraphAttributeValue>
}

export interface StoryGraphEventEffect {
  entity_id: string
  attribute: string
  new_value?: string | number | boolean | null
}

export interface StoryGraphEvent {
  id: string
  story_order: number
  scene_id: string
  summary: string
  status?: string
  participant_ids?: string[]
  effects?: StoryGraphEventEffect[]
}

export interface StoryGraphAsset {
  id: string
  kind: string
  signed_url?: string
  qa_notes?: string
}

export interface StoryGraphAppearance {
  id: string
  entity_id: string
  state_label: string
  version: number
  status: string
  visual_description?: string
  wardrobe?: string
  assets?: StoryGraphAsset[]
}

export interface StoryGraphInteractionStep {
  step_index: number
  actor_id: string
  action_verb: string
  target_id?: string | null
  target_kind?: string
  pre_state?: string
  contact_mechanics?: string
  post_state?: string
  supported_by?: string
  environment_reaction?: string
  sound_trigger?: string
  description: string
}

export interface StoryGraphClipScript {
  clip_index: number
  duration_s: number
  omni_prompt: string
  step_indices: number[]
  dialogue_line_ids: string[]
  opening_state: string
  closing_state: string
}

export interface StoryGraphScene {
  id: string
  index: number
  location_id: string
  time_of_day?: string
  heading?: string
  summary?: string
  status?: string
  interaction_steps?: StoryGraphInteractionStep[]
  ambient_environment_cue?: string
  weather_and_air?: string
  clips?: StoryGraphClipScript[]
}

export interface StoryGraphDialogueLine {
  id: string
  shot_id?: string
  speaker_id: string
  delivery?: string
  language?: string
  text: string
}

export interface StoryGraphMusicCue {
  id: string
  mood: string
  instrumentation?: string
  tempo_bpm?: number
  foley_palette?: string[]
  environmental_ambience?: string
  action_focus_sfx?: string[]
}

export interface StoryGraphBeat {
  t_start_s: number
  t_end_s: number
  description: string
  pre_state?: string
  post_state?: string
}

export interface StoryGraphCastEntry {
  entity_id: string
  position?: string
  appearance_id?: string
}

export interface StoryGraphCameraSpec {
  shot_size?: string
  angle?: string
  movement?: string
  lens_mm?: number
}

export interface StoryGraphLightingSpec {
  key: string
  fill: string
  practicals: string
  direction: string
  quality: string
}

export interface StoryGraphColorGradeSpec {
  shades: string[]
  contrast: string
  saturation: string
  temperature: string
}

export interface StoryGraphShotLook {
  lighting: StoryGraphLightingSpec
  color_grade: StoryGraphColorGradeSpec
  mood: string
  composition: string
  camera_motion_intent: string
}

export interface StoryGraphShot {
  id: string
  scene_id: string
  story_order: number
  duration_s: number
  status?: string
  camera?: StoryGraphCameraSpec
  continue_from_last_frame?: boolean
  beats?: StoryGraphBeat[]
  cast?: StoryGraphCastEntry[]
  prop_ids?: string[]
  dialogue_ids?: string[]
  music_cue_id?: string
  foley_sfx?: string[]
  environmental_sfx?: string[]
  action_focus_sfx?: string[]
  entry_motion_vector?: string
  exit_motion_vector?: string
  clip_index?: number | null
  look?: StoryGraphShotLook | null
}

export interface StoryGraphQaScores {
  wardrobe_match: number
  setting_match: number
  action_achieved: number
  physics_plausibility?: number
  object_permanence?: number
  dialogue_wer: number
}

export interface StoryGraphGenerationRun {
  id: string
  shot_id: string
  attempt: number
  model?: string
  provider?: string
  seed?: number
  status: string
  output_video_signed_url?: string
  first_frame_asset_id?: string
  reference_asset_ids?: string[]
  extracted_last_frame_asset_id?: string
  qa_scores?: StoryGraphQaScores
  compiled_prompt?: string
}

export interface StoryGraphGate {
  gate_id: string
  decision: string
}

export interface StoryGraphStageRun {
  stage: string
  completed?: boolean
  status?: string
  error?: string
  duration_s?: number
  images_generated?: number
  videos_generated?: number
}

export interface StoryGraphChangeRequest {
  id: string
  from_role: string
  to_role: string
  target_node_id: string
  reason: string
}

export interface StoryGraphAuditEntry {
  id: string
  role: string
  tool: string
  target_id: string
  after_version: number
}

export type StoryGraphStateFact = Record<string, unknown>

/** Shot whose latest generation run is approved and can be stitched by S10. */
export interface ReadyShot {
  shot_id: string
  run_id: string
  video_uri: string
}

/** Shot preventing a strict S10 assembly (not approved / flagged by QA). */
export interface BlockingShot {
  shot_id: string
  latest_status: string
  failure_reasons: string[]
  artifact_flags: string[]
}

/** GET /productions/{id}/assembly-readiness response. */
export interface AssemblyReadiness {
  ready_shots: ReadyShot[]
  blocking: BlockingShot[]
  is_complete: boolean
}

export type AssembleMode = 'approved_only' | 'strict'

export interface StoryGraphValidationIssue {
  code: string
  severity: string
  node_id: string
  message: string
}

export interface StoryGraphStageQaIssue {
  code: string
  severity: string
  node_id: string
  message: string
  remediation_applied?: string
}

export interface StoryGraphStageQaReport {
  stage: string
  agent_role: string
  iteration: number
  passed: boolean
  score: number
  summary: string
  issues: StoryGraphStageQaIssue[]
}

export interface StoryGraphData {
  style_guide?: StoryGraphStyleGuide
  entities: {
    characters: StoryGraphEntity[]
    locations: StoryGraphEntity[]
    objects: StoryGraphEntity[]
    all: StoryGraphEntity[]
  }
  events: StoryGraphEvent[]
  state_facts: StoryGraphStateFact[]
  appearances: StoryGraphAppearance[]
  assets: StoryGraphAsset[]
  scenes: StoryGraphScene[]
  dialogue_lines: StoryGraphDialogueLine[]
  music_cues: StoryGraphMusicCue[]
  shots: StoryGraphShot[]
  generation_runs: StoryGraphGenerationRun[]
  gates: StoryGraphGate[]
  stage_runs: StoryGraphStageRun[]
  stage_qa_reports?: StoryGraphStageQaReport[]
  validation_issues: StoryGraphValidationIssue[]
  change_requests: StoryGraphChangeRequest[]
  audit_log: StoryGraphAuditEntry[]
}
