import type { TimeRange } from '@/types/insights'
import { formatTimecode } from '@/types/timeline/timeFormat'
import type { TimeScale } from '@/types/timeline/viewport'

export interface SpanBox {
  /** Left edge of the item, possibly left of the plot. */
  x: number
  /** Full width of the item in pixels (at least 1). */
  width: number
  /** Left edge of the part that is inside the plot. */
  visibleX: number
  /** Width of the part that is inside the plot. */
  visibleWidth: number
}

/** Pixel box of a time range, plus the part of it that lies inside the plot (for labels). */
export function spanBox(scale: TimeScale, range: TimeRange): SpanBox {
  const x = scale.toX(range.start_sec)
  const right = scale.toX(range.end_sec)
  const visibleX = Math.max(x, 0)
  const visibleWidth = Math.max(Math.min(right, scale.width) - visibleX, 0)
  return { x, width: Math.max(right - x, 1), visibleX, visibleWidth }
}

/** "0:07 to 0:12", for accessible item names. */
export function spokenRange(range: TimeRange): string {
  return `${formatTimecode(range.start_sec)} to ${formatTimecode(range.end_sec)}`
}
