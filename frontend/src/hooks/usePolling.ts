import { useState, useEffect } from 'react'

function getRecordStatus(record: unknown): string | undefined {
  if (record && typeof record === 'object' && 'status' in record) {
    const val = (record as { status?: unknown }).status
    return typeof val === 'string' ? val : undefined
  }
  return undefined
}

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
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  const currentStatus = getRecordStatus(record)

  // Poll while status is active
  useEffect(() => {
    if (!id || !record || !currentStatus) return
    if (!activeStatuses.includes(currentStatus)) return

    const timer = setInterval(async () => {
      try {
        const updated = await fetchFn(id)
        setRecord(updated)
        const nextStatus = getRecordStatus(updated)
        if (!nextStatus || !activeStatuses.includes(nextStatus)) {
          clearInterval(timer)
        }
      } catch {
        // ignore poll errors
      }
    }, interval)

    return () => clearInterval(timer)
  }, [id, currentStatus])

  return { record, loading, error }
}
