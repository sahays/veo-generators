export interface StoryGraphStyleGuide {
  id?: string
  visual_medium?: string
  lens_language?: string
  lighting_rules?: string
  palette?: string[]
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

export interface StoryGraphScene {
  id: string
  index: number
  location_id: string
  time_of_day?: string
  heading?: string
  summary?: string
  status?: string
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
}

export interface StoryGraphBeat {
  t_start_s: number
  t_end_s: number
  description: string
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
  dialogue_ids?: string[]
  music_cue_id?: string
}

export interface StoryGraphQaScores {
  wardrobe_match: number
  setting_match: number
  action_achieved: number
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

export interface StoryGraphValidationIssue {
  code: string
  severity: string
  node_id: string
  message: string
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
  validation_issues: StoryGraphValidationIssue[]
  change_requests: StoryGraphChangeRequest[]
  audit_log: StoryGraphAuditEntry[]
}
