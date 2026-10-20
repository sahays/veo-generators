import type { StoryGraphStageRun } from '@/types/project'
import type { ActiveStepId, MacroStepCardDef } from '../storyGraphStudioTypes'
import type { CascadeProgress } from '../cascade/useStageCascade'
import { PIPELINE_SUB_STAGES } from '../cascade/pipelineStages'

export type StepState = 'done' | 'running' | 'failed' | 'attention' | 'pending'
export type ChipTone = 'default' | 'accent' | 'success' | 'warning' | 'destructive'

export interface StatusChip {
  label: string
  tone: ChipTone
}

export interface StudioRunState {
  completedStages: Set<string>
  latestStageRunByStage: Record<string, StoryGraphStageRun>
  busyAction: string | null
  isRunning: boolean
  pipelineStatus?: string
  pendingGate: string | null
  activeError: string | null
}

function isStageFailed(run?: StoryGraphStageRun): boolean {
  return run?.status === 'failed' || !!run?.error
}

/** Visual state of one macro step in the stepper. */
export function deriveStepState(card: MacroStepCardDef, s: StudioRunState): StepState {
  if (s.busyAction && card.stages.includes(s.busyAction)) return 'running'
  if (card.stages.some((st) => isStageFailed(s.latestStageRunByStage[st]))) return 'failed'
  if (card.id === 's8_s10_videos' && s.pipelineStatus === 'needs_review') return 'attention'
  return card.stages.every((st) => s.completedStages.has(st)) ? 'done' : 'pending'
}

/** First macro step that still has work to do (falls back to the last step). */
export function firstOpenStep(cards: MacroStepCardDef[], completed: Set<string>): ActiveStepId {
  const open = cards.find((c) => !c.stages.every((st) => completed.has(st)))
  return (open ?? cards[cards.length - 1])?.id ?? 's1_world'
}

/** Single overall production status chip. */
export function deriveStatusChip(s: StudioRunState, hasFinalCut: boolean): StatusChip {
  if (s.isRunning || s.busyAction) return { label: 'Running', tone: 'accent' }
  if (s.activeError) return { label: 'Needs attention', tone: 'destructive' }
  if (s.pipelineStatus === 'needs_review') return { label: 'Needs review', tone: 'warning' }
  if (s.pendingGate || s.pipelineStatus?.startsWith('awaiting_')) return { label: 'Awaiting approval', tone: 'warning' }
  if (s.pipelineStatus === 'completed_partial') return { label: 'Partial cut', tone: 'warning' }
  if (hasFinalCut || s.pipelineStatus === 'completed') return { label: 'Completed', tone: 'success' }
  return { label: s.completedStages.size > 0 ? 'In progress' : 'Draft', tone: 'default' }
}

export type NextActionKind = 'busy' | 'retry' | 'continue' | 'review' | 'stitch' | 'upgrade' | 'view'

export interface NextAction {
  kind: NextActionKind
  label: string
  stage?: string
  step?: ActiveStepId
}

function busyLabel(s: StudioRunState, cascade?: CascadeProgress | null): string {
  if (cascade) return `Regenerating ${cascade.index}/${cascade.total} · ${cascade.label}`
  const sub = PIPELINE_SUB_STAGES.find((x) => x.id === s.busyAction)
  return sub ? `Running ${sub.label}…` : 'Running…'
}

/** Context-aware single primary action for the header. */
export function deriveNextAction(
  s: StudioRunState,
  ctx: { failedStage: string | null; hasFinalCut: boolean; renderQuality?: string; cascade?: CascadeProgress | null },
): NextAction {
  if (s.isRunning || s.busyAction) return { kind: 'busy', label: busyLabel(s, ctx.cascade) }
  if (ctx.failedStage) return { kind: 'retry', label: 'Retry failed step', stage: ctx.failedStage }
  if (s.pipelineStatus === 'needs_review') return { kind: 'review', label: 'Review shots', step: 's8_s10_videos' }
  const allButAssemble = PIPELINE_SUB_STAGES.slice(0, -1).every((x) => s.completedStages.has(x.id))
  if (allButAssemble && !ctx.hasFinalCut) return { kind: 'stitch', label: 'Stitch final cut', stage: 'S10_ASSEMBLE' }
  if (ctx.hasFinalCut && ctx.renderQuality !== 'final') return { kind: 'upgrade', label: 'Render 720p final', stage: 'S8_RENDER' }
  if (ctx.hasFinalCut) return { kind: 'view', label: 'Watch final cut', step: 's8_s10_videos' }
  return { kind: 'continue', label: s.completedStages.size > 0 ? 'Continue production' : 'Start production' }
}
