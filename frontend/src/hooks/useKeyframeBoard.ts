import { useCallback, useEffect, useState } from 'react'
import { keyframes } from '@/lib/api/keyframes'
import type { KeyframeBoardResponse } from '@/types/keyframes'
import type { RunAccepted } from '@/types/runs'

/** Starts an async (202) S8 run and resolves when it completes; rejects with the run error. */
export type KeyframeRunTask = (label: string, call: () => Promise<RunAccepted>) => Promise<unknown>

export interface PendingRegen {
  shotId: string
  t: number
}

export interface KeyframeBoardState {
  board: KeyframeBoardResponse | null
  isLoading: boolean
  loadError: string | null
  pending: PendingRegen | null
  regenError: string | null
  isResuming: boolean
  resumeError: string | null
  regenerate: (shotId: string, t: number, instruction?: string) => Promise<boolean>
  resume: () => Promise<boolean>
  refresh: () => void
}

const errorText = (err: unknown, fallback: string): string => (err instanceof Error ? err.message : fallback)

function useBoardFetch(productionId: string, refreshKey: string, nonce: number) {
  const [board, setBoard] = useState<KeyframeBoardResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    keyframes
      .getBoard(productionId)
      .then((res) => { if (!cancelled) { setBoard(res); setLoadError(null) } })
      .catch((err: unknown) => { if (!cancelled) { setBoard(null); setLoadError(errorText(err, 'Failed to load keyframes')) } })
      .finally(() => { if (!cancelled) setIsLoading(false) })
    return () => { cancelled = true }
  }, [productionId, refreshKey, nonce])
  return { board, isLoading, loadError }
}

function useResumeFlow(productionId: string, runTask: KeyframeRunTask, onDone: () => void) {
  const [isResuming, setIsResuming] = useState(false)
  const [resumeError, setResumeError] = useState<string | null>(null)

  const resume = useCallback(async (): Promise<boolean> => {
    setIsResuming(true)
    setResumeError(null)
    try {
      await runTask('Resume keyframes', () => keyframes.resume(productionId))
      onDone()
      return true
    } catch (err) {
      setResumeError(errorText(err, 'Failed to resume keyframes'))
      return false
    } finally {
      setIsResuming(false)
    }
  }, [productionId, runTask, onDone])

  return { isResuming, resumeError, resume }
}

/**
 * Loads the S8_KEYFRAMES board for a production (re-fetched when `refreshKey` changes,
 * e.g. after a stage run) and exposes per-frame "regenerate from t" (t = the keyframe's event time).
 * Regenerate and resume are async runs (`runTask`); the whole board is re-fetched when they finish
 * because later clips of the scene re-derive too.
 */
export function useKeyframeBoard(productionId: string, refreshKey: string, runTask: KeyframeRunTask): KeyframeBoardState {
  const [nonce, setNonce] = useState(0)
  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  const { board, isLoading, loadError } = useBoardFetch(productionId, refreshKey, nonce)
  const [pending, setPending] = useState<PendingRegen | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)
  const { isResuming, resumeError, resume } = useResumeFlow(productionId, runTask, refresh)

  const regenerate = useCallback(async (shotId: string, t: number, instruction?: string): Promise<boolean> => {
    setPending({ shotId, t })
    setRegenError(null)
    try {
      await runTask(`Regenerate ${shotId} keyframes from t=${t}s`, () => keyframes.regenerateFrom(productionId, shotId, t, { instruction }))
      refresh()
      return true
    } catch (err) {
      setRegenError(errorText(err, 'Failed to regenerate keyframes'))
      return false
    } finally {
      setPending(null)
    }
  }, [productionId, runTask, refresh])

  return { board, isLoading, loadError, pending, regenError, isResuming, resumeError, regenerate, resume, refresh }
}
