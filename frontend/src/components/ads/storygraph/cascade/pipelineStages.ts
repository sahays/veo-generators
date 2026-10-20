import type { ActiveStepId } from '../storyGraphStudioTypes'

export type StageRenderQuality = 'draft' | 'final'

export interface PipelineSubStage {
  id: string
  short: string
  label: string
  role: string
  stepGroup: ActiveStepId
}

export const PIPELINE_SUB_STAGES: PipelineSubStage[] = [
  { id: 'S1_EXTRACT', short: 'A1', label: 'Story Architect', role: 'STORY_ARCHITECT + SUPERVISOR', stepGroup: 's1_world' },
  { id: 'S2_SCREENPLAY', short: 'A2', label: 'Screenplay Writer', role: 'ALGORITHMIC SCREENWRITER', stepGroup: 's2_scripts' },
  { id: 'S3_DESIGN', short: 'A3', label: 'Design Studio', role: 'CHAR / LOC / OBJ DESIGNERS', stepGroup: 's3_images' },
  { id: 'S4_SHOTS', short: 'A4', label: 'Film Director', role: 'DIRECTOR AGENT', stepGroup: 's4_s5_shots' },
  { id: 'S5_MUSIC', short: 'A4b', label: 'Music & Foley Director', role: 'MUSIC + FOLEY + SFX', stepGroup: 's4_s5_shots' },
  { id: 'S6_VALIDATE', short: 'A5', label: 'O(V+E) Graph Verifier', role: '3× REVIEW + REDO + V1–V13', stepGroup: 's6_s7_compile' },
  { id: 'S7_COMPILE', short: 'A5b', label: 'Prompt Compiler', role: 'BUDGETER + JINJA2', stepGroup: 's6_s7_compile' },
  { id: 'S8_RENDER', short: 'A6', label: 'Cinematographer (Veo)', role: 'GEMINI OMNI / VEO', stepGroup: 's8_s10_videos' },
  { id: 'S9_QA', short: 'A6b', label: 'Physics & Clip VLM Critic', role: 'PHYSICS + PERMANENCE QA', stepGroup: 's8_s10_videos' },
  { id: 'S10_ASSEMBLE', short: 'A6c', label: 'Master Editor', role: 'FFMPEG ASSEMBLER', stepGroup: 's8_s10_videos' },
]

/** A user request to regenerate `stageId` (and everything downstream of it). */
export interface CascadeRequest {
  stageId: string
  quality?: StageRenderQuality
}

/** One stage execution inside a regenerate cascade. */
export interface CascadeStep {
  stageId: string
  short: string
  label: string
  force: boolean
  quality?: StageRenderQuality
  /** True when the backend runs this stage itself (forced S8 cascades S9/S10 server-side). */
  serverRun: boolean
}

/** Stages whose forced run already cascades the rest of the pipeline on the server. */
const SERVER_CASCADING_STAGES = new Set(['S8_RENDER'])

/**
 * Ordered plan: the clicked stage runs with `force=true` (and the requested render
 * quality, if any); every downstream stage runs with `force=false` so the backend can
 * skip unchanged stages by input hash and re-render only invalidated shots.
 */
export function buildCascadePlan(req: CascadeRequest): CascadeStep[] {
  const start = PIPELINE_SUB_STAGES.findIndex((s) => s.id === req.stageId)
  if (start < 0) {
    return [{ stageId: req.stageId, short: '', label: req.stageId, force: true, quality: req.quality, serverRun: false }]
  }
  const serverCascades = SERVER_CASCADING_STAGES.has(req.stageId)
  return PIPELINE_SUB_STAGES.slice(start).map((sub, i) => ({
    stageId: sub.id,
    short: sub.short,
    label: sub.label,
    force: i === 0,
    quality: i === 0 ? req.quality : undefined,
    serverRun: serverCascades && i > 0,
  }))
}

const GATE_BLOCK_RE = /blocked by unapproved gate\s*(G\d)?/i
const REVIEW_BLOCK_RE = /assembly blocked by (\d+) unapproved|needs[_ ]review/i

/** Readable message when final assembly is blocked by shots that failed QA. */
export function reviewStopMessage(step: CascadeStep, failedCount?: number): string {
  const count = failedCount === undefined ? 'some' : String(failedCount)
  return `Paused at ${step.label}: ${count} shot(s) failed QA. Use “Repair failed shots” in the Videos step, edit flagged shots, or stitch approved shots only.`
}

/**
 * Classify a stage error as a graceful stop (gate block / shots awaiting review).
 * Returns a readable message for graceful stops, or `null` for a hard failure.
 */
export function classifyCascadeStop(message: string, step: CascadeStep): string | null {
  const gate = GATE_BLOCK_RE.exec(message)
  if (gate) {
    const gateId = gate[1] ? ` ${gate[1]}` : ''
    return `Regeneration paused at ${step.label}: approval gate${gateId} must be approved before continuing.`
  }
  const review = REVIEW_BLOCK_RE.exec(message)
  if (!review) return null
  return reviewStopMessage(step, review[1] ? Number(review[1]) : undefined)
}
