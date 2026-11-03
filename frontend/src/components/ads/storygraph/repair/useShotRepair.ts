import { useCallback, useState } from 'react'
import type { Project } from '@/types/project'
import type { ShotRepairReport } from '@/types/storygraph'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import type { RunAccepted } from '@/types/runs'
import { runToCompletion, useRunPoller } from '../run/ProductionRunContext'

/** Matches the API layer's 422 `ApiValidationError` (structural check keeps UI off the API tier). */
const validationIssuesOf = (err: unknown): string[] | null => {
  const issues = err instanceof Error ? (err as Error & { issues?: unknown }).issues : undefined
  return Array.isArray(issues) ? issues.map(String) : null
}

const REPAIR_STAGE = 'S8_REPAIR'

/** `RunView.result.repair_report` of a finished repair run (shape-checked, else null). */
const repairReportOf = (result: Record<string, unknown> | null): ShotRepairReport | null => {
  const report = result?.repair_report
  return report && typeof report === 'object' && Array.isArray((report as ShotRepairReport).outcomes)
    ? (report as ShotRepairReport)
    : null
}

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
 * Both are async (202) runs tracked by the studio poller; the graph is re-read when they finish.
 * `onSettled` fires after every attempt so callers can refresh readiness.
 */
export function useShotRepair(
  productionId: string,
  onGraphUpdated: (snapshot: Project) => void,
  onSettled: () => void,
): ShotRepairState {
  const { projects } = useAdsProjectActions()
  const poller = useRunPoller()
  const [isRepairing, setIsRepairing] = useState(false)
  const [regeneratingShotId, setRegeneratingShotId] = useState<string | null>(null)
  const [repairError, setRepairError] = useState<string | null>(null)
  const [report, setReport] = useState<ShotRepairReport | null>(null)
  const [editIssues, setEditIssues] = useState<Record<string, string[]>>({})

  const runRepairRequest = useCallback(async (label: string, call: () => Promise<RunAccepted>) => {
    const done = await runToCompletion(poller, label, REPAIR_STAGE, call)
    onGraphUpdated((await projects.get(productionId)) as unknown as Project)
    setReport(repairReportOf(done.result))
  }, [poller, projects, productionId, onGraphUpdated])

  const repairFailed = useCallback(async (shotIds: string[]) => {
    setIsRepairing(true)
    setRepairError(null)
    setReport(null)
    try {
      await runRepairRequest('Repair failed shots', () => projects.repairShots(productionId, shotIds))
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
      await runRepairRequest(`Regenerate ${shotId}`, () => projects.regenerateShot(productionId, shotId))
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
