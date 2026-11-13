import { useEffect, useRef, useState } from 'react'

export interface AsyncResource<T> {
  /** The loaded value; null until the first load succeeds. */
  data: T | null
  error: string | null
  /** Load again, e.g. from a "Try again" button. */
  reload: () => void
}

/**
 * Loads a document once per `key` (a record id) and again on `reload()`.
 * A response that arrives after the key changed or the component unmounted
 * is dropped. `load` may be an inline function: only `key` triggers a reload.
 */
export function useAsyncResource<T>(load: () => Promise<T>, key: string, fallbackError: string): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const latest = useRef({ load, fallbackError })
  latest.current = { load, fallbackError }

  useEffect(() => {
    let current = true
    setError(null)
    latest.current
      .load()
      .then((value) => current && setData(value))
      .catch((cause: unknown) => current && setError(cause instanceof Error ? cause.message : latest.current.fallbackError))
    return () => {
      current = false
    }
  }, [key, attempt])

  return { data, error, reload: () => setAttempt((n) => n + 1) }
}
