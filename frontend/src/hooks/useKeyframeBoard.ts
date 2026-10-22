import { useCallback, useEffect, useState } from 'react'
import { keyframes } from '@/lib/api/keyframes'
import type { KeyframeBoardResponse, KeyframeStripResponse } from '@/types/keyframes'

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
  regenerate: (shotId: string, t: number, instruction?: string) => Promise<boolean>
  refresh: () => void
}

const errorText = (err: unknown, fallback: string): string => (err instanceof Error ? err.message : fallback)

function replaceStrip(board: KeyframeBoardResponse | null, strip: KeyframeStripResponse): KeyframeBoardResponse | null {
  if (!board) return board
  return { ...board, shots: board.shots.map((s) => (s.shot_id === strip.shot_id ? strip : s)) }
}

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
  return { board, setBoard, isLoading, loadError }
}

/**
 * Loads the S8_KEYFRAMES board for a production (re-fetched when `refreshKey` changes,
 * e.g. after a stage run) and exposes per-frame "regenerate from t". The returned strip is
 * applied in place, then the board is re-fetched because later clips of the scene re-derive too.
 */
export function useKeyframeBoard(productionId: string, refreshKey: string): KeyframeBoardState {
  const [nonce, setNonce] = useState(0)
  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  const { board, setBoard, isLoading, loadError } = useBoardFetch(productionId, refreshKey, nonce)
  const [pending, setPending] = useState<PendingRegen | null>(null)
  const [regenError, setRegenError] = useState<string | null>(null)

  const regenerate = useCallback(async (shotId: string, t: number, instruction?: string): Promise<boolean> => {
    setPending({ shotId, t })
    setRegenError(null)
    try {
      const strip = await keyframes.regenerateFrom(productionId, shotId, t, { instruction })
      setBoard((prev) => replaceStrip(prev, strip))
      refresh()
      return true
    } catch (err) {
      setRegenError(errorText(err, 'Failed to regenerate keyframes'))
      return false
    } finally {
      setPending(null)
    }
  }, [productionId, refresh, setBoard])

  return { board, isLoading, loadError, pending, regenError, regenerate, refresh }
}
