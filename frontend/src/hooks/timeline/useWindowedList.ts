import { useCallback, useEffect, useMemo, useState } from 'react'
import { computeWindow, prefixOffsets, scrollTopToReveal, type ListWindow } from '@/types/timeline/windowing'
import { useElementSize } from './useElementSize'

/** Scroll offset of an element, updated at most once per animation frame. */
function useScrollTop(node: HTMLElement | null): number {
  const [scrollTop, setScrollTop] = useState(0)
  useEffect(() => {
    if (!node) return
    let frame = 0
    const onScroll = (): void => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        setScrollTop(node.scrollTop)
      })
    }
    node.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      node.removeEventListener('scroll', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [node])
  return scrollTop
}

export interface WindowedList {
  /** Put on the scroll container (it needs a fixed or max height and `overflow-y: auto`). */
  containerRef: (node: HTMLDivElement | null) => void
  /** Rows to mount and the spacer heights around them. */
  window: ListWindow
  /** Content width of the container, for estimating row heights. */
  width: number
  /** Scroll the container (never the page) so row `index` is visible. */
  reveal: (index: number) => void
}

/**
 * Windowed rendering for a long list of rows with estimated heights.
 * Render `<div style={{height: window.padTop}} />`, the rows
 * `[window.start, window.end)` in normal flow, then
 * `<div style={{height: window.padBottom}} />`.
 */
export function useWindowedList(heights: readonly number[], overscanPx = 240): WindowedList {
  const [containerRef, size, node] = useElementSize<HTMLDivElement>()
  const scrollTop = useScrollTop(node)
  const offsets = useMemo(() => prefixOffsets(heights), [heights])
  const listWindow = useMemo(
    () => computeWindow(offsets, scrollTop, size.height, overscanPx),
    [offsets, scrollTop, size.height, overscanPx],
  )
  const reveal = useCallback(
    (index: number): void => {
      if (!node) return
      const top = scrollTopToReveal(offsets, index, node.scrollTop, node.clientHeight)
      if (top !== null) node.scrollTop = top
    },
    [node, offsets],
  )
  return { containerRef, window: listWindow, width: size.width, reveal }
}
