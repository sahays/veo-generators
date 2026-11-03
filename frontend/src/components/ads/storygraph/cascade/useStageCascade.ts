import { useCallback, useState } from 'react'
import { stageLabel } from '../run/runLogic'
import type { StartStage } from '../run/useStudioRunCommands'
import type { CascadeRequest, StageRenderQuality } from './pipelineStages'
import type { StudioProjectsApi } from './stageRunner'

export interface CascadeDeps {
  projectsApi: StudioProjectsApi
  productionId: string
  /** Shared run starter (optimistic state, 409 sync, error banner). */
  startStage: StartStage
  /** A run is live or starting: confirmation is not offered. */
  isLocked: boolean
}

/** Position inside a multi-stage server run (shown in the header while it runs). */
export interface CascadeProgress {
  index: number
  total: number
  stageId: string
  label: string
}

/**
 * Confirm-then-run "regenerate stage + downstream". `requestCascade` opens the confirmation;
 * `confirmCascade` issues ONE `runStage(stage, force=true, quality, cascade=true)` call — the
 * server runs every downstream stage (non-forced) and stops gracefully at gates / review.
 */
export function useStageCascade({ projectsApi, productionId, startStage, isLocked }: CascadeDeps) {
  const [pendingRequest, setPendingRequest] = useState<CascadeRequest | null>(null)

  const requestCascade = useCallback((stageId: string, quality?: StageRenderQuality) => {
    if (!isLocked) setPendingRequest({ stageId, quality })
  }, [isLocked])

  const cancelCascade = useCallback(() => setPendingRequest(null), [])

  const confirmCascade = useCallback(async (): Promise<void> => {
    if (!pendingRequest) return
    const { stageId, quality } = pendingRequest
    setPendingRequest(null)
    await startStage(`Regenerate ${stageLabel(stageId)}`, stageId, () =>
      projectsApi.runStage(productionId, stageId, true, quality, true))
  }, [pendingRequest, projectsApi, productionId, startStage])

  return { pendingRequest, requestCascade, cancelCascade, confirmCascade }
}
