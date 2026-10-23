import { useCallback, useEffect, useRef, useState } from 'react'

export interface LazyDetail<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

/**
 * Fetch an on-demand detail resource (kept out of the snapshot) whenever `key` changes.
 * Pass `key = null` to skip loading. Stale responses from a previous key are ignored.
 */
export function useLazyDetail<T>(key: string | null, load: () => Promise<T>): LazyDetail<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [nonce, setNonce] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load
  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (key === null) return
    let cancelled = false
    setLoading(true)
    setError(null)
    loadRef.current()
      .then((res) => { if (!cancelled) setData(res) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [key, nonce])

  return { data, error, loading, reload }
}
