import { useCallback, useState } from 'react'
import type { Project } from '@/types/project'
import type { ShotRepairReport } from '@/types/storygraph'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import { runStageRequestWithRecovery } from '../cascade/stageRunner'

/** Matches the API layer's 422 `ApiValidationError` (structural check keeps UI off the API tier). */
const validationIssuesOf = (err: unknown): string[] | null => {
  const issues = err instanceof Error ? (err as Error & { issues?: unknown }).issues : undefined
  return Array.isArray(issues) ? issues.map(String) : null
}

const REPAIR_STAGE = 'S8_REPAIR'

export interface ShotRepairState {
  isRepairing: boolean
  /** Shot currently being saved + regenerated from the manual editor. */
  regeneratingShotId: string | null
  repairError: string | null
  report: ShotRepairReport | null
  /** 422 validation issues from the last clip edit, keyed by shot id. */
  editIssues: Record<string, string[]>
  repairFailed: (shotIds: string[]) => Promise<void>
  saveAndRegenerate: (shotId: string, omniPrompt: string) => Promise<boolean>
  clearEditIssues: (shotId: string) => void
}

const errorText = (err: unknown, fallback: string): string => (err instanceof Error ? err.message : fallback)

/**
 * Failed-shot repair actions for the Videos step: bulk automatic repair (S8_REPAIR) and
 * manual "edit clip prompt → regenerate" for shots flagged after exhausting repairs.
 * Both survive proxy timeouts by polling the graph for the S8_REPAIR stage run.
 * `onSettled` fires after every attempt so callers can refresh readiness.
 */
export function useShotRepair(
  productionId: string,
  onGraphUpdated: (snapshot: Project) => void,
  onSettled: () => void,
): ShotRepairState {
  const { projects } = useAdsProjectActions()
  const [isRepairing, setIsRepairing] = useState(false)
  const [regeneratingShotId, setRegeneratingShotId] = useState<string | null>(null)
  const [repairError, setRepairError] = useState<string | null>(null)
  const [report, setReport] = useState<ShotRepairReport | null>(null)
  const [editIssues, setEditIssues] = useState<Record<string, string[]>>({})

  const runRepairRequest = useCallback(async (call: () => ReturnType<typeof projects.repairShots>) => {
    const res = await runStageRequestWithRecovery(projects, productionId, REPAIR_STAGE, call, onGraphUpdated)
    if (!res) return
    onGraphUpdated(res)
    if (res.repair_report) setReport(res.repair_report)
  }, [projects, productionId, onGraphUpdated])

  const repairFailed = useCallback(async (shotIds: string[]) => {
    setIsRepairing(true)
    setRepairError(null)
    setReport(null)
    try {
      await runRepairRequest(() => projects.repairShots(productionId, shotIds))
    } catch (err) {
      setRepairError(errorText(err, 'Failed to repair shots'))
    } finally {
      setIsRepairing(false)
      onSettled()
    }
  }, [projects, productionId, runRepairRequest, onSettled])

  const clearEditIssues = useCallback((shotId: string) => {
    setEditIssues((prev) => {
      const next = { ...prev }
      delete next[shotId]
      return next
    })
  }, [])

  const saveAndRegenerate = useCallback(async (shotId: string, omniPrompt: string): Promise<boolean> => {
    setRegeneratingShotId(shotId)
    setRepairError(null)
    clearEditIssues(shotId)
    try {
      onGraphUpdated(await projects.updateShotClip(productionId, shotId, { omni_prompt: omniPrompt }))
      await runRepairRequest(() => projects.regenerateShot(productionId, shotId))
      return true
    } catch (err) {
      const issues = validationIssuesOf(err)
      if (issues) setEditIssues((prev) => ({ ...prev, [shotId]: issues }))
      else setRepairError(errorText(err, `Failed to regenerate ${shotId}`))
      return false
    } finally {
      setRegeneratingShotId(null)
      onSettled()
    }
  }, [projects, productionId, onGraphUpdated, runRepairRequest, clearEditIssues, onSettled])

  return { isRepairing, regeneratingShotId, repairError, report, editIssues, repairFailed, saveAndRegenerate, clearEditIssues }
}
