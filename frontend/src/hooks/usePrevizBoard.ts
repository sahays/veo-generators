import { useCallback, useEffect, useRef, useState } from 'react'
import { previz } from '@/lib/api/previz'
import type { PrevizBoardResponse, PrevizRestyleVariant, PrevizRunPayload, ShotPreviz } from '@/types/previz'

export const PREVIZ_POLL_MS = 5000
/** Polls granted right after a run is accepted, before the backend reports `running`. */
export const PREVIZ_START_GRACE_POLLS = 3

const isShotActive = (shot: ShotPreviz): boolean =>
  shot.status === 'running' || shot.variants.some((v) => v.status === 'running')

/** True while the backend still has previz work in flight (stage run, any shot, or any variant). */
export function isPrevizActive(board: PrevizBoardResponse | null): boolean {
  if (!board) return false
  return board.stage_run?.status === 'running' || board.shots.some(isShotActive)
}

/**
 * Delay before the next poll, or `null` to stop. `graceLeft` keeps polling briefly after a
 * run is accepted so a backend that has not flipped to `running` yet is not missed.
 */
export function nextPollDelay(board: PrevizBoardResponse | null, graceLeft: number): number | null {
  return isPrevizActive(board) || graceLeft > 0 ? PREVIZ_POLL_MS : null
}

export interface PendingPromote {
  shotId: string
  variant: PrevizRestyleVariant
}

export interface PrevizBoardState {
  board: PrevizBoardResponse | null
  isLoading: boolean
  loadError: string | null
  isStarting: boolean
  pendingPromote: PendingPromote | null
  actionError: string | null
  run: (payload: PrevizRunPayload) => Promise<boolean>
  promote: (shotId: string, variant: PrevizRestyleVariant) => Promise<boolean>
  clearActionError: () => void
}

const errorText = (err: unknown, fallback: string): string => (err instanceof Error ? err.message : fallback)

function replaceShot(board: PrevizBoardResponse | null, shot: ShotPreviz): PrevizBoardResponse | null {
  if (!board) return board
  return { ...board, shots: board.shots.map((s) => (s.shot_id === shot.shot_id ? shot : s)) }
}

/** One `GET /previz` per `tick`; `settled` increments after every attempt (success or error). */
function useBoardFetch(productionId: string, tick: number) {
  const [board, setBoard] = useState<PrevizBoardResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [settled, setSettled] = useState(0)
  useEffect(() => {
    let cancelled = false
    previz
      .getBoard(productionId)
      .then((res) => { if (!cancelled) { setBoard(res); setLoadError(null) } })
      .catch((err: unknown) => { if (!cancelled) setLoadError(errorText(err, 'Failed to load previz')) })
      .finally(() => { if (!cancelled) { setIsLoading(false); setSettled((n) => n + 1) } })
    return () => { cancelled = true }
  }, [productionId, tick])
  return { board, setBoard, isLoading, loadError, settled, setSettled }
}

/**
 * Initial load + chained polling (setTimeout after each settled fetch, so requests never
 * overlap). While the tab is hidden the timer re-arms without hitting the network.
 */
function usePolledBoard(productionId: string) {
  const [tick, setTick] = useState(0)
  const graceRef = useRef(0)
  const refresh = useCallback(() => setTick((n) => n + 1), [])
  const fetched = useBoardFetch(productionId, tick)
  const { board, settled, setSettled } = fetched
  useEffect(() => {
    const delay = settled > 0 ? nextPollDelay(board, graceRef.current) : null
    if (delay === null) return
    const id = window.setTimeout(() => {
      if (document.visibilityState === 'hidden') return setSettled((n) => n + 1)
      graceRef.current = Math.max(0, graceRef.current - 1)
      refresh()
    }, delay)
    return () => window.clearTimeout(id)
  }, [board, settled, setSettled, refresh])
  const startGrace = useCallback(() => { graceRef.current = PREVIZ_START_GRACE_POLLS }, [])
  return { ...fetched, refresh, startGrace }
}

function useRunAction(productionId: string, onAccepted: () => void, setActionError: (e: string | null) => void) {
  const [isStarting, setIsStarting] = useState(false)
  const run = useCallback(async (payload: PrevizRunPayload): Promise<boolean> => {
    setIsStarting(true)
    setActionError(null)
    try {
      await previz.run(productionId, payload)
      onAccepted()
      return true
    } catch (err) {
      setActionError(errorText(err, 'Failed to start previz run'))
      return false
    } finally {
      setIsStarting(false)
    }
  }, [productionId, onAccepted, setActionError])
  return { isStarting, run }
}

/** Blender previz board for one production: polling, run, and per-variant promote. */
export function usePrevizBoard(productionId: string): PrevizBoardState {
  const { board, setBoard, isLoading, loadError, refresh, startGrace } = usePolledBoard(productionId)
  const [pendingPromote, setPendingPromote] = useState<PendingPromote | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const onAccepted = useCallback(() => { startGrace(); refresh() }, [startGrace, refresh])
  const { isStarting, run } = useRunAction(productionId, onAccepted, setActionError)

  const promote = useCallback(async (shotId: string, variant: PrevizRestyleVariant): Promise<boolean> => {
    setPendingPromote({ shotId, variant })
    setActionError(null)
    try {
      const shot = await previz.promote(productionId, shotId, { variant })
      setBoard((prev) => replaceShot(prev, shot))
      refresh()
      return true
    } catch (err) {
      setActionError(errorText(err, 'Failed to promote render'))
      return false
    } finally {
      setPendingPromote(null)
    }
  }, [productionId, refresh, setBoard])

  const clearActionError = useCallback(() => setActionError(null), [])
  return { board, isLoading, loadError, isStarting, pendingPromote, actionError, run, promote, clearActionError }
}
