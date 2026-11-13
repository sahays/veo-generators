import { useEffect, useRef } from 'react'
import type { TimeScale, Viewport } from '@/types/timeline/viewport'
import type { ViewportApi } from './useTimelineViewport'

const LINE_HEIGHT_PX = 16
const ZOOM_PER_WHEEL_PX = 0.002
const DRAG_THRESHOLD_PX = 4

/** Elements carrying this attribute handle their own pointer input (ruler scrubbing, minimap brush). */
export const NO_PAN_ATTR = 'data-tl-nopan'

export interface GestureEnv {
  scale: TimeScale
  api: ViewportApi
  /** Client x of the left edge of the plot area (right edge of the label gutter). */
  plotLeft: () => number
}

interface PendingWheel {
  factor: number
  anchorSec: number
  panSec: number
  frame: number
}

function applyWheel(pending: PendingWheel, api: ViewportApi): void {
  if (pending.factor !== 1) api.zoomAt(pending.factor, pending.anchorSec)
  if (pending.panSec !== 0) api.panBy(pending.panSec)
  pending.factor = 1
  pending.panSec = 0
  pending.frame = 0
}

/** Fold one wheel event into the pending frame. Vertical wheel zooms about the cursor; horizontal or Shift pans. */
function accumulateWheel(event: WheelEvent, env: GestureEnv, pending: PendingWheel): boolean {
  const x = event.clientX - env.plotLeft()
  if (x < 0 || x > env.scale.width || env.scale.pxPerSec <= 0) return false
  const unit = event.deltaMode === 1 ? LINE_HEIGHT_PX : 1
  const dx = event.deltaX * unit
  const dy = event.deltaY * unit
  if (event.shiftKey || Math.abs(dx) > Math.abs(dy)) {
    pending.panSec += (dx || dy) / env.scale.pxPerSec
    return true
  }
  pending.factor *= Math.exp(-dy * ZOOM_PER_WHEEL_PX)
  pending.anchorSec = env.scale.toTime(x)
  return true
}

/** Wheel listener that coalesces events into one viewport update per animation frame. */
function bindWheel(target: HTMLElement, env: () => GestureEnv): () => void {
  const pending: PendingWheel = { factor: 1, anchorSec: 0, panSec: 0, frame: 0 }
  const onWheel = (event: WheelEvent): void => {
    if (!accumulateWheel(event, env(), pending)) return
    event.preventDefault()
    if (!pending.frame) pending.frame = requestAnimationFrame(() => applyWheel(pending, env().api))
  }
  // Not passive: the page must not scroll while the wheel zooms the timeline.
  target.addEventListener('wheel', onWheel, { passive: false })
  return () => {
    target.removeEventListener('wheel', onWheel)
    if (pending.frame) cancelAnimationFrame(pending.frame)
  }
}

interface DragState {
  pointerId: number
  startX: number
  startView: Viewport
  dragging: boolean
}

function beginDrag(event: PointerEvent, env: GestureEnv): DragState | null {
  const origin = event.target instanceof Element ? event.target : null
  if (event.button !== 0 || !origin || origin.closest(`[${NO_PAN_ATTR}]`)) return null
  if (event.clientX < env.plotLeft()) return null
  return { pointerId: event.pointerId, startX: event.clientX, startView: env.api.getView(), dragging: false }
}

function continueDrag(event: PointerEvent, drag: DragState, env: GestureEnv, target: HTMLElement): void {
  const dx = event.clientX - drag.startX
  if (!drag.dragging && Math.abs(dx) < DRAG_THRESHOLD_PX) return
  if (!drag.dragging) {
    drag.dragging = true
    // Capturing only once the pointer has moved keeps plain clicks on lane items working.
    target.setPointerCapture(event.pointerId)
  }
  const shift = -dx / env.scale.pxPerSec
  env.api.setView({ start: drag.startView.start + shift, end: drag.startView.end + shift })
}

/** Drag on the plot area pans the viewport. */
function bindPan(target: HTMLElement, env: () => GestureEnv): () => void {
  let drag: DragState | null = null
  const onDown = (event: PointerEvent): void => {
    drag = beginDrag(event, env())
  }
  const onMove = (event: PointerEvent): void => {
    if (drag && event.pointerId === drag.pointerId) continueDrag(event, drag, env(), target)
  }
  const onEnd = (): void => {
    drag = null
  }
  target.addEventListener('pointerdown', onDown)
  target.addEventListener('pointermove', onMove)
  target.addEventListener('pointerup', onEnd)
  target.addEventListener('pointercancel', onEnd)
  return () => {
    target.removeEventListener('pointerdown', onDown)
    target.removeEventListener('pointermove', onMove)
    target.removeEventListener('pointerup', onEnd)
    target.removeEventListener('pointercancel', onEnd)
  }
}

/**
 * Wheel-to-zoom (about the cursor) and drag-to-pan for a timeline surface.
 * Listeners are bound once per element; the latest scale is read through a
 * ref, so zooming does not re-bind them.
 */
export function useTimelineGestures(target: HTMLElement | null, env: GestureEnv): void {
  const latest = useRef(env)
  latest.current = env

  useEffect(() => {
    if (!target) return
    const read = (): GestureEnv => latest.current
    const unbindWheel = bindWheel(target, read)
    const unbindPan = bindPan(target, read)
    return () => {
      unbindWheel()
      unbindPan()
    }
  }, [target])
}
