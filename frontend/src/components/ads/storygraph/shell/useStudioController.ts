import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronsDownUp, ChevronsUpDown, Pencil, Sparkles, Wrench } from 'lucide-react'
import type { StoryGraphData } from '@/types/project'
import type { ActiveStepId, MacroStepCardDef, deriveStageAndGateMaps, useStoryGraphStudioActions } from '../storyGraphStudioTypes'
import { PIPELINE_SUB_STAGES } from '../cascade/pipelineStages'
import type { StudioMenuItem } from './StudioHeader'
import { deriveNextAction, deriveStatusChip, deriveStepState, firstOpenStep, type NextAction, type StudioRunState } from './studioStatus'

export type StudioTab = 'pipeline' | 'advanced'

export interface StudioControllerInput {
  storyGraph?: StoryGraphData
  pipelineStatus?: string
  finalVideoUrl?: string
  renderQuality?: 'draft' | 'final'
  canWrite: boolean
  onEditBrief?: () => void
  actions: ReturnType<typeof useStoryGraphStudioActions>
  stageMaps: ReturnType<typeof deriveStageAndGateMaps>
  cards: MacroStepCardDef[]
}

function useStepExpansion(cards: MacroStepCardDef[], completed: Set<string>) {
  const [activeStep, setActiveStep] = useState<ActiveStepId | null>(() => firstOpenStep(cards, completed))
  const [expandAll, setExpandAll] = useState(false)
  const isExpanded = useCallback((id: ActiveStepId) => expandAll || activeStep === id, [expandAll, activeStep])
  const toggle = useCallback((id: ActiveStepId, open: boolean) => {
    setExpandAll(false)
    setActiveStep(open ? id : null)
  }, [])
  const focus = useCallback((id: ActiveStepId) => {
    setExpandAll(false)
    setActiveStep(id)
    requestAnimationFrame(() => document.getElementById(`step-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }, [])
  return { isExpanded, toggle, focus, expandAll, setExpandAll }
}

function buildRunState(i: StudioControllerInput): StudioRunState {
  return {
    completedStages: i.stageMaps.completedStages,
    latestStageRunByStage: i.stageMaps.latestStageRunByStage,
    busyAction: i.actions.busyAction,
    isRunning: i.actions.isRunningPipeline,
    pipelineStatus: i.pipelineStatus,
    pendingGate: i.stageMaps.pendingGate,
    activeError: i.stageMaps.activeError,
  }
}

function runNextAction(a: NextAction, i: StudioControllerInput, focus: (id: ActiveStepId) => void, setTab: (t: StudioTab) => void) {
  if (a.kind === 'busy') return
  if (a.kind === 'retry' && a.stage) return void i.actions.handleRetryStage(a.stage)
  if (a.kind === 'continue') return void i.actions.handleRunForward()
  if (a.kind === 'stitch') return i.actions.handleRunStage('S10_ASSEMBLE')
  if (a.kind === 'upgrade') return i.actions.handleRunStage('S8_RENDER', 'final')
  if (a.step) {
    setTab('pipeline')
    focus(a.step)
  }
}

function buildMenu(i: StudioControllerInput, exp: ReturnType<typeof useStepExpansion>, tab: StudioTab, setTab: (t: StudioTab) => void): StudioMenuItem[] {
  const busy = i.actions.isRunningPipeline || i.actions.busyAction !== null
  const items: StudioMenuItem[] = [
    { id: 'run-all', label: 'Run all remaining agents', icon: Sparkles, onSelect: () => void i.actions.handleRunForward(), disabled: busy || !i.canWrite },
    { id: 'expand', label: exp.expandAll ? 'Collapse all steps' : 'Expand all steps', icon: exp.expandAll ? ChevronsDownUp : ChevronsUpDown, onSelect: () => exp.setExpandAll((v) => !v), separatorBefore: true },
    { id: 'advanced', label: tab === 'advanced' ? 'Back to pipeline' : 'Advanced tools', icon: Wrench, onSelect: () => setTab(tab === 'advanced' ? 'pipeline' : 'advanced') },
  ]
  if (i.onEditBrief && i.canWrite) items.push({ id: 'edit', label: 'Edit brief', icon: Pencil, onSelect: i.onEditBrief, separatorBefore: true })
  return items
}

/** View-model for the studio shell: status, primary action, step states, menu, expansion. */
export function useStudioController(i: StudioControllerInput) {
  const [tab, setTab] = useState<StudioTab>('pipeline')
  const exp = useStepExpansion(i.cards, i.stageMaps.completedStages)
  const runState = buildRunState(i)
  const hasFinalCut = !!i.finalVideoUrl
  const nextAction = deriveNextAction(runState, {
    failedStage: i.actions.failedStage, hasFinalCut, renderQuality: i.renderQuality, cascade: i.actions.cascade.progress,
  })
  const followRef = useRef<string | null>(null)
  const busyStep = PIPELINE_SUB_STAGES.find((s) => s.id === i.actions.busyAction)?.stepGroup ?? null
  const { focus } = exp
  useEffect(() => {
    if (busyStep && followRef.current !== busyStep) focus(busyStep)
    followRef.current = busyStep
  }, [busyStep, focus])
  return {
    tab, setTab, ...exp,
    status: deriveStatusChip(runState, hasFinalCut),
    progress: { done: PIPELINE_SUB_STAGES.filter((s) => runState.completedStages.has(s.id)).length, total: PIPELINE_SUB_STAGES.length },
    stepItems: i.cards.map((card) => ({ card, state: deriveStepState(card, runState) })),
    nextAction,
    onNextAction: () => runNextAction(nextAction, i, exp.focus, setTab),
    menuItems: buildMenu(i, exp, tab, setTab),
  }
}
