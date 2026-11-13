import { useEffect, useState } from 'react'

export interface ElementSize {
  width: number
  height: number
}

const EMPTY: ElementSize = { width: 0, height: 0 }

/**
 * Content-box size of an element, kept current with a ResizeObserver.
 * Returns a ref callback to put on the element and its latest size.
 */
export function useElementSize<T extends HTMLElement>(): [(node: T | null) => void, ElementSize, T | null] {
  const [node, setNode] = useState<T | null>(null)
  const [size, setSize] = useState<ElementSize>(EMPTY)

  useEffect(() => {
    if (!node) return
    const measure = (): void => {
      const next = { width: node.clientWidth, height: node.clientHeight }
      setSize((prev) => (prev.width === next.width && prev.height === next.height ? prev : next))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [node])

  return [setNode, size, node]
}
