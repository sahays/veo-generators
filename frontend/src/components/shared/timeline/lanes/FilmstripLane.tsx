import { useTimeScale } from '@/hooks/timeline/timelineContext'
import type { FilmstripInfo } from '@/types/insights'
import type { TimeScale } from '@/types/timeline/viewport'
import { LANE_HEIGHT } from '../layout'
import { TimelineLane } from '../TimelineLane'

const HEIGHT = LANE_HEIGHT.filmstrip

interface Thumb {
  key: number
  x: number
  /** Top-left of the tile inside the sprite, in sprite pixels. */
  spriteX: number
  spriteY: number
}

/**
 * Thumbnails to draw for the visible range. Slots have a fixed pixel width
 * and are anchored in time, so they slide with the timeline when it pans;
 * each shows the sprite tile nearest to the middle of its slot. Only the
 * slots intersecting the viewport are produced.
 */
function visibleThumbs(scale: TimeScale, strip: FilmstripInfo, slotPx: number): Thumb[] {
  if (scale.pxPerSec <= 0 || strip.count <= 0 || strip.interval_sec <= 0) return []
  const slotSec = slotPx / scale.pxPerSec
  const first = Math.floor(scale.view.start / slotSec)
  const last = Math.ceil(scale.view.end / slotSec)
  const thumbs: Thumb[] = []
  for (let slot = first; slot < last; slot++) {
    const frame = Math.round(((slot + 0.5) * slotSec) / strip.interval_sec)
    const tile = Math.min(Math.max(frame, 0), strip.count - 1)
    thumbs.push({
      key: slot,
      x: scale.toX(slot * slotSec),
      spriteX: (tile % strip.columns) * strip.tile_width,
      spriteY: Math.floor(tile / strip.columns) * strip.tile_height,
    })
  }
  return thumbs
}

function FilmstripPlot({ filmstrip }: { filmstrip: FilmstripInfo }): JSX.Element {
  const scale = useTimeScale()
  const slotPx = Math.max((HEIGHT * filmstrip.tile_width) / Math.max(filmstrip.tile_height, 1), 1)
  const thumbs = visibleThumbs(scale, filmstrip, slotPx)
  const tileBox = `${filmstrip.tile_width} ${filmstrip.tile_height}`
  return (
    <svg role="img" aria-label="Video thumbnails" width={scale.width} height={HEIGHT} className="block bg-muted/40">
      {thumbs.map((thumb) => (
        <svg key={thumb.key} x={thumb.x} width={slotPx} height={HEIGHT} viewBox={`${thumb.spriteX} ${thumb.spriteY} ${tileBox}`} preserveAspectRatio="none">
          <image href={filmstrip.url} width={filmstrip.columns * filmstrip.tile_width} height={filmstrip.rows * filmstrip.tile_height} />
        </svg>
      ))}
    </svg>
  )
}

export interface FilmstripLaneProps {
  /** Sprite description from `TimelineResponse.filmstrip`; the lane is omitted when null. */
  filmstrip: FilmstripInfo | null
  id?: string
  label?: string
}

/** Thumbnail strip cut from the filmstrip sprite (tile `i` is the frame at `i * interval_sec`). */
export function FilmstripLane({ filmstrip, id = 'filmstrip', label = 'Filmstrip' }: FilmstripLaneProps): JSX.Element | null {
  if (!filmstrip) return null
  return (
    <TimelineLane id={id} label={label} height={HEIGHT}>
      <FilmstripPlot filmstrip={filmstrip} />
    </TimelineLane>
  )
}
