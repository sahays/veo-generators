import { useCallback, useRef, useState } from 'react'
import type { Project } from '@/types/project'
import {
  buildCascadePlan,
  classifyCascadeStop,
  reviewStopMessage,
  type CascadeRequest,
  type CascadeStep,
  type StageRenderQuality,
} from './pipelineStages'
import { runStageWithRecovery, type StudioProjectsApi } from './stageRunner'

export interface CascadeDeps {
  projectsApi: StudioProjectsApi
  productionId: string
  onGraphUpdated: (snapshot: Project) => void
  setBusyAction: (s: string | null) => void
  setFailedStage: (s: string | null) => void
  setErrorMsg: (s: string | null) => void
}

export interface CascadeProgress {
  index: number
  total: number
  stageId: string
  label: string
}

type StepOutcome = 'continue' | 'stop'

async function runCascadeStep(step: CascadeStep, deps: CascadeDeps): Promise<StepOutcome> {
  try {
    const snap = await runStageWithRecovery(
      deps.projectsApi, deps.productionId, step.stageId, step.force, deps.onGraphUpdated, step.quality,
    )
    deps.onGraphUpdated(snap)
    if (step.stageId === 'S10_ASSEMBLE' && snap.status === 'needs_review') {
      deps.setErrorMsg(reviewStopMessage(step))
      return 'stop'
    }
    return 'continue'
  } catch (err) {
    const msg = err instanceof Error ? err.message : `Stage ${step.stageId} failed`
    const graceful = classifyCascadeStop(msg, step)
    if (!graceful) deps.setFailedStage(step.stageId)
    deps.setErrorMsg(graceful ?? msg)
    return 'stop'
  }
}

async function executeCascade(
  plan: CascadeStep[],
  deps: CascadeDeps,
  setProgress: (p: CascadeProgress | null) => void,
): Promise<void> {
  deps.setErrorMsg(null)
  deps.setFailedStage(null)
  for (const [i, step] of plan.entries()) {
    setProgress({ index: i + 1, total: plan.length, stageId: step.stageId, label: step.label })
    deps.setBusyAction(step.stageId)
    if ((await runCascadeStep(step, deps)) === 'stop') return
  }
}

/**
 * Confirm-then-run "regenerate stage + downstream" orchestration for the studio.
 * `requestCascade` opens the confirmation; `confirmCascade` executes the plan sequentially,
 * stopping on the first failure or graceful gate/review block.
 */
export function useStageCascade(deps: CascadeDeps) {
  const [pendingRequest, setPendingRequest] = useState<CascadeRequest | null>(null)
  const [progress, setProgress] = useState<CascadeProgress | null>(null)
  const runningRef = useRef(false)

  const requestCascade = useCallback((stageId: string, quality?: StageRenderQuality) => {
    if (!runningRef.current) setPendingRequest({ stageId, quality })
  }, [])

  const cancelCascade = useCallback(() => setPendingRequest(null), [])

  const confirmCascade = async (): Promise<void> => {
    if (!pendingRequest || runningRef.current) return
    const plan = buildCascadePlan(pendingRequest).filter((step) => !step.serverRun)
    setPendingRequest(null)
    runningRef.current = true
    try {
      await executeCascade(plan, deps, setProgress)
    } finally {
      runningRef.current = false
      setProgress(null)
      deps.setBusyAction(null)
    }
  }

  return { pendingRequest, progress, isCascading: progress !== null, requestCascade, cancelCascade, confirmCascade }
}
