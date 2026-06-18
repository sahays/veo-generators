import { useMemo, useState } from 'react'

const ts = (r: unknown): number => {
  const c = (r as { createdAt?: string })?.createdAt
  return c ? new Date(c).getTime() : 0
}

/**
 * Client-side "show latest N, then load more" pagination.
 *
 * Sorts newest-first (by `createdAt` when present) and reveals `pageSize` items
 * at a time. The full list is already in memory — this only controls how many
 * are rendered.
 */
export function useShowMore<T>(items: T[], pageSize = 10, sortNewest = true) {
  const [count, setCount] = useState(pageSize)

  const ordered = useMemo(
    () => (sortNewest ? [...items].sort((a, b) => ts(b) - ts(a)) : items),
    [items, sortNewest],
  )

  const visible = ordered.slice(0, count)
  const hasMore = count < ordered.length
  const remaining = ordered.length - count
  const showMore = () => setCount((c) => c + pageSize)

  return { visible, hasMore, remaining, showMore }
}
