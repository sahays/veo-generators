import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { RunAccepted } from '@/types/runs'
import { PIPELINE_SUB_STAGES, type StageRenderQuality } from '../cascade/pipelineStages'
import type { StudioProjectsApi } from '../cascade/stageRunner'
import type { CascadeProgress } from '../cascade/useStageCascade'
import type { RunPoller, RunSnapshot } from './runPoller'
import { runSequencePosition, stageLabel } from './runLogic'
import { selectBusyKey, selectLocked, startRun, useRunSelector, useRunTransitions } from './ProductionRunContext'

export type StartStage = (label: string, stage: string | null, call: () => Promise<RunAccepted>) => Promise<boolean>

interface RunCommandDeps {
  poller: RunPoller | null
  projectsApi: StudioProjectsApi
  productionId: string
  completedStages?: Set<string>
  setErrorMsg: (msg: string | null) => void
}

/** Primitive key for the planned-sequence position, so the studio re-renders on stage change only. */
const selectSequenceKey = (s: RunSnapshot): string | null => {
  const run = s.status?.active_run ?? null
  const pos = runSequencePosition(run)
  return pos && run?.stage ? `${pos.index}|${pos.total}|${run.stage}` : null
}

function parseSequenceKey(key: string | null): CascadeProgress | null {
  if (!key) return null
  const [index, total, stageId] = key.split('|')
  return { index: Number(index), total: Number(total), stageId, label: stageLabel(stageId) }
}

/** Remember the stage of the last hard failure so the header can offer "Retry failed step". */
function useFailedStage(poller: RunPoller | null) {
  const [failedStage, setFailedStage] = useState<string | null>(null)
  useRunTransitions(poller, (t) => {
    if (t.started) setFailedStage(null)
    if (t.finished?.status === 'failed') setFailedStage(t.finished.stage)
  })
  return { failedStage, setFailedStage }
}

/**
 * Studio-level run commands. Every long action is ONE async server call (202) tracked by the
 * shared poller — no client-side stage loops, no request held open for minutes.
 */
export function useStudioRunCommands({ poller, projectsApi, productionId, completedStages, setErrorMsg }: RunCommandDeps) {
  const busyKey = useRunSelector(poller, selectBusyKey)
  const isRunning = useRunSelector(poller, selectLocked)
  const sequenceKey = useRunSelector(poller, selectSequenceKey)
  const sequence = useMemo(() => parseSequenceKey(sequenceKey), [sequenceKey])
  const { failedStage, setFailedStage } = useFailedStage(poller)
  const completedRef = useRef(completedStages)
  useEffect(() => { completedRef.current = completedStages }, [completedStages])

  const startStage = useCallback<StartStage>(async (label, stage, call) => {
    setErrorMsg(null)
    setFailedStage(null)
    const res = await startRun(poller, label, stage, call)
    if (!res.ok && !res.conflict) { setErrorMsg(res.error); setFailedStage(stage) }
    return res.ok
  }, [poller, setErrorMsg, setFailedStage])

  /**
   * "Run all remaining agents": one non-forced cascade from the first incomplete stage. Same
   * semantics as the old per-stage loop (force=false, project gate setting honoured, stops at gates).
   */
  const runForward = useCallback(async (): Promise<void> => {
    await poller?.ready()
    const first = PIPELINE_SUB_STAGES.find((s) => !completedRef.current?.has(s.id))
    if (!first || poller?.isLocked()) return
    await startStage('Run remaining agents', first.id, () => projectsApi.runStage(productionId, first.id, false, undefined, true))
  }, [poller, projectsApi, productionId, startStage])

  const retryStage = useCallback((stage: string, quality?: StageRenderQuality) =>
    startStage(`Re-run ${stageLabel(stage)}`, stage, () => projectsApi.runStage(productionId, stage, true, quality, false)),
  [projectsApi, productionId, startStage])

  const regenerateAppearance = useCallback((appearanceId: string) =>
    startStage('Regenerate reference sheet', null, () => projectsApi.regenerateAppearance(productionId, appearanceId)),
  [projectsApi, productionId, startStage])

  return { busyKey, isRunning, sequence, failedStage, startStage, runForward, retryStage, regenerateAppearance }
}
