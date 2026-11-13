import { useEffect, useRef } from 'react'
import { useTimeScale, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'

/**
 * Playhead line across all lanes. It is positioned by a clock subscription
 * that writes a CSS transform, so playback moves it without any React render.
 * The effect re-runs only when the scale changes (zoom, pan, resize).
 */
export function Playhead(): JSX.Element {
  const { clock } = useTimelineKit()
  const scale = useTimeScale()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const place = (): void => {
      const node = ref.current
      if (!node) return
      const x = scale.toX(clock.getTime())
      node.style.transform = `translate3d(${x.toFixed(2)}px, 0, 0)`
      node.style.visibility = x >= -1 && x <= scale.width + 1 ? 'visible' : 'hidden'
    }
    place()
    return clock.subscribeTime(place)
  }, [clock, scale])

  return (
    <div ref={ref} aria-hidden data-testid="timeline-playhead" className="absolute inset-y-0 left-0 z-10 w-0 will-change-transform">
      <div className="absolute inset-y-0 -left-px w-0.5 bg-accent shadow-[0_0_6px_rgba(249,115,22,0.6)]" />
      <div className="absolute -left-[5px] top-0 h-0 w-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-accent" />
    </div>
  )
}

/** Shaded band over all lanes for the selected item or range. */
export function SelectionBand(): JSX.Element | null {
  const range = useWorkspace((state) => state.selection?.range)
  const scale = useTimeScale()
  if (!range) return null
  const x0 = scale.toX(range.start_sec)
  const x1 = scale.toX(range.end_sec)
  if (x1 < 0 || x0 > scale.width) return null
  const left = Math.max(x0, 0)
  const width = Math.max(Math.min(x1, scale.width) - left, 1)
  return (
    <div
      aria-hidden
      data-testid="timeline-selection"
      className="absolute inset-y-0 border-x border-accent/60 bg-accent/10"
      style={{ left, width }}
    />
  )
}
