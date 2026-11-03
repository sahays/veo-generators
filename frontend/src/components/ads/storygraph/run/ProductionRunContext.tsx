import { createContext, useContext, useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { api } from '@/hooks/useApiClient'
import type { RunAccepted, RunView } from '@/types/runs'
import { RunPoller, type RunSnapshot, type StartResult } from './runPoller'
import { runBusyKey, type RunTransition, type StartingRun } from './runLogic'

/** One poller per mounted studio; provided to every panel below it. */
export const ProductionRunContext = createContext<RunPoller | null>(null)

/** Create (once per production) and drive the status poller for the studio's lifetime. */
export function useRunPollerInstance(productionId: string): RunPoller {
  const poller = useMemo(() => new RunPoller(productionId, api.runs.getStatus), [productionId])
  useEffect(() => {
    poller.start()
    return () => poller.stop()
  }, [poller])
  return poller
}

/** The studio's poller, or `null` outside a `ProductionRunContext` provider. */
export function useRunPoller(): RunPoller | null {
  return useContext(ProductionRunContext)
}

const NOOP_SUBSCRIBE = (): (() => void) => () => undefined
const EMPTY_SNAPSHOT: RunSnapshot = { status: null, skewMs: 0, starting: null, notice: null, terminal: null }

/**
 * Subscribe to a slice of the run snapshot. `select` must return a primitive or a reference
 * held by the snapshot so components re-render only when that slice changes.
 */
export function useRunSelector<T>(poller: RunPoller | null, select: (s: RunSnapshot) => T): T {
  const get = (): T => select(poller ? poller.getSnapshot() : EMPTY_SNAPSHOT)
  return useSyncExternalStore(poller ? poller.subscribe : NOOP_SUBSCRIBE, get, get)
}

export const selectActiveRun = (s: RunSnapshot): RunView | null => s.status?.active_run ?? null
export const selectStarting = (s: RunSnapshot): StartingRun | null => s.starting
export const selectLocked = (s: RunSnapshot): boolean => s.starting !== null || (s.status?.active_run ?? null) !== null
export const selectLockLabel = (s: RunSnapshot): string => s.status?.active_run?.label ?? s.starting?.label ?? ''
export const selectBusyKey = (s: RunSnapshot): string | null => runBusyKey(s.status?.active_run ?? null, s.starting)

/** Start a run through the studio poller (optimistic state, 409 sync); errors when no studio is mounted. */
export function startRun(
  poller: RunPoller | null,
  label: string,
  stage: string | null,
  call: () => Promise<RunAccepted>,
): Promise<StartResult> {
  if (!poller) return Promise.resolve({ ok: false, conflict: false, error: 'Run tracking is unavailable outside the studio' })
  return poller.run(label, stage, call)
}

/**
 * Start a run and resolve with its finished `RunView` once the poller sees it settle.
 * Throws with the server's message when the start is rejected or the run does not complete.
 */
export async function runToCompletion(
  poller: RunPoller | null,
  label: string,
  stage: string | null,
  call: () => Promise<RunAccepted>,
): Promise<RunView> {
  const res = await startRun(poller, label, stage, call)
  if (!res.ok) throw new Error(res.error)
  const done = poller ? await poller.waitFor(res.run.run_id) : null
  if (!done) throw new Error(`${label}: lost track of the run; refresh to see its outcome`)
  if (done.status !== 'completed') throw new Error(done.error ?? `${label} ${done.status}`)
  return done
}

/** Run a callback for every stage-change / completion transition (callback may change identity). */
export function useRunTransitions(poller: RunPoller | null, onTransition: (t: RunTransition) => void): void {
  const handler = useRef(onTransition)
  useEffect(() => { handler.current = onTransition })
  useEffect(() => (poller ? poller.onTransition((t) => handler.current(t)) : undefined), [poller])
}
