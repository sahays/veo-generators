import { useState, useEffect } from 'react'

export function usePolling<T>(
  id: string | undefined,
  fetchFn: (id: string) => Promise<T>,
  activeStatuses: string[],
  interval: number = 5000
): { record: T | null; loading: boolean; error: string | null } {
  const [record, setRecord] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Initial load
  useEffect(() => {
    if (!id) return
    setLoading(true)
    fetchFn(id)
      .then(setRecord)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  // Poll while status is active
  useEffect(() => {
    if (!id || !record) return
    const status = (record as any).status
    if (!activeStatuses.includes(status)) return

    const timer = setInterval(async () => {
      try {
        const updated = await fetchFn(id)
        setRecord(updated)
        if (!activeStatuses.includes((updated as any).status)) {
          clearInterval(timer)
        }
      } catch {
        // ignore poll errors
      }
    }, interval)

    return () => clearInterval(timer)
  }, [id, (record as any)?.status])

  return { record, loading, error }
}
