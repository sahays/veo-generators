import { useCallback, useEffect, useState } from 'react'
import type { Project } from '@/types/project'
import type { AssemblyReadiness } from '@/types/storygraph'
import { useAdsProjectActions } from '../projects/useAdsProjectActions'
import { runToCompletion, useRunPoller } from './run/ProductionRunContext'

const ASSEMBLE_STAGE = 'S10_ASSEMBLE'

export interface AssemblyReadinessState {
  readiness: AssemblyReadiness | null
  isAssembling: boolean
  assembleError: string | null
  assembleApprovedOnly: () => Promise<void>
  /** Force a readiness re-fetch (e.g. after a repair run settles). */
  refresh: () => void
}

/**
 * Loads S10 assembly readiness for a production and exposes the
 * "stitch approved shots only" action. Readiness is re-fetched whenever
 * `refreshKey` changes (e.g. generation-run statuses or pipeline status)
 * or `refresh()` is called.
 */
export function useAssemblyReadiness(
  productionId: string,
  refreshKey: string,
  onGraphUpdated: (snapshot: Project) => void,
): AssemblyReadinessState {
  const { projects } = useAdsProjectActions()
  const poller = useRunPoller()
  const [readiness, setReadiness] = useState<AssemblyReadiness | null>(null)
  const [isAssembling, setIsAssembling] = useState(false)
  const [assembleError, setAssembleError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    projects
      .getAssemblyReadiness(productionId)
      .then((res) => { if (!cancelled) setReadiness(res) })
      .catch(() => { if (!cancelled) setReadiness(null) })
    return () => { cancelled = true }
  }, [projects, productionId, refreshKey, nonce])

  const assembleApprovedOnly = useCallback(async () => {
    setIsAssembling(true)
    setAssembleError(null)
    try {
      await runToCompletion(poller, 'Stitch approved shots', ASSEMBLE_STAGE, () =>
        projects.assembleApprovedShots(productionId, 'approved_only'),
      )
      const snapshot = await projects.getStoryGraph(productionId)
      onGraphUpdated(snapshot as unknown as Project)
    } catch (err) {
      setAssembleError(err instanceof Error ? err.message : 'Failed to stitch approved shots')
    } finally {
      setIsAssembling(false)
      refresh()
    }
  }, [poller, projects, productionId, onGraphUpdated, refresh])

  return { readiness, isAssembling, assembleError, assembleApprovedOnly, refresh }
}
