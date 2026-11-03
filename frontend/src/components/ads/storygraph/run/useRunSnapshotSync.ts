import { useCallback, useEffect, useRef } from 'react'
import type { Project } from '@/types/project'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import type { RunPoller } from './runPoller'
import { useRunTransitions } from './ProductionRunContext'

/**
 * Re-fetch the (heavy) graph snapshot ONLY when the live run changes stage or finishes —
 * never per poll tick. Overlapping triggers are coalesced into one trailing refresh.
 */
export function useRunSnapshotSync(poller: RunPoller | null, productionId: string, onGraphUpdated: (snap: Project) => void): void {
  const { projects } = useAdsProjectActions()
  const onUpdate = useRef(onGraphUpdated)
  useEffect(() => { onUpdate.current = onGraphUpdated })
  const gate = useRef({ inFlight: false, dirty: false })

  const refresh = useCallback(async (): Promise<void> => {
    if (gate.current.inFlight) { gate.current.dirty = true; return }
    gate.current.inFlight = true
    try {
      do {
        gate.current.dirty = false
        const snap = (await projects.getStoryGraph(productionId)) as Project | null
        if (snap?.id) onUpdate.current(snap)
      } while (gate.current.dirty)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      poller?.reportError(`Failed to refresh studio snapshot: ${msg}`)
    } finally {
      gate.current.inFlight = false
    }
  }, [poller, projects, productionId])

  useRunTransitions(poller, (t) => { if (t.stageChanged || t.finished) void refresh() })
}
