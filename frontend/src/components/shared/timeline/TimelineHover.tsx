import { useEffect, useState } from 'react'
import { useTimeScale } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'

const CARD_OFFSET_PX = 14

/**
 * Pointer x within the plot (whole pixels), or null when the pointer is
 * outside it or a button is held (dragging). Listening happens on the lanes
 * element because the overlay itself ignores pointer events.
 */
function useHoverX(target: HTMLElement | null, plot: HTMLElement | null): number | null {
  const [hoverX, setHoverX] = useState<number | null>(null)

  useEffect(() => {
    if (!target || !plot) return
    const onMove = (event: PointerEvent): void => {
      const rect = plot.getBoundingClientRect()
      const x = Math.round(event.clientX - rect.left)
      const inside = x >= 0 && x <= rect.width && event.buttons === 0 && event.pointerType !== 'touch'
      setHoverX(inside ? x : null)
    }
    const onLeave = (): void => setHoverX(null)
    target.addEventListener('pointermove', onMove)
    target.addEventListener('pointerleave', onLeave)
    return () => {
      target.removeEventListener('pointermove', onMove)
      target.removeEventListener('pointerleave', onLeave)
    }
  }, [target, plot])

  return hoverX
}

export interface HoverLayerProps {
  /** Element that receives pointer events (the lanes container). */
  target: HTMLElement | null
  /** The plot overlay, used to convert client x into plot x. */
  plot: HTMLElement | null
  render: (timeSec: number) => React.ReactNode
}

/**
 * Crosshair and hover card. Hover state lives here, inside the overlay, so
 * moving the pointer re-renders this component only, never the lanes.
 */
export function HoverLayer({ target, plot, render }: HoverLayerProps): JSX.Element | null {
  const scale = useTimeScale()
  const hoverX = useHoverX(target, plot)
  if (hoverX === null || scale.width <= 0) return null
  const onRightHalf = hoverX > scale.width / 2
  const cardStyle = onRightHalf ? { right: scale.width - hoverX + CARD_OFFSET_PX } : { left: hoverX + CARD_OFFSET_PX }

  return (
    <>
      <div aria-hidden className="absolute inset-y-0 left-0 z-10 w-px bg-foreground/45" style={{ transform: `translateX(${hoverX}px)` }} />
      <div
        data-testid="timeline-hover-card"
        className={cn(
          'absolute top-8 z-20 w-64 rounded-lg border border-border bg-popover p-2.5 text-xs text-popover-foreground shadow-xl',
        )}
        style={cardStyle}
      >
        {render(scale.toTime(hoverX))}
      </div>
    </>
  )
}
