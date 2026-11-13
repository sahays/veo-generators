import { useEffect } from 'react'
import type { TimeRange } from '@/types/insights'
import type { IntervalIndex } from '@/types/timeline/intervalIndex'
import { segmentJumpTarget, shortcutForKey, type ShortcutAction } from '@/types/timeline/shortcuts'
import { useSeek, useTimelineKit } from './timelineContext'

const EDITABLE = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]'
/** Widgets that use Space themselves. */
const SPACE_OWNERS = 'button, a[href], summary, [role="button"], [role="checkbox"], [role="switch"], [role="tab"], [role="menuitem"]'
/** Widgets that use the arrow keys themselves; timeline lanes opt in with `data-tl-arrows`. */
const ARROW_OWNERS = '[role="tablist"], [role="menu"], [role="listbox"], [role="slider"], [role="radiogroup"], [data-tl-arrows]'

function ownedByWidget(event: KeyboardEvent): boolean {
  const target = event.target instanceof Element ? event.target : null
  if (!target) return false
  if (target.closest(EDITABLE)) return true
  if (event.key === ' ') return target.closest(SPACE_OWNERS) !== null
  if (event.key.startsWith('Arrow')) return target.closest(ARROW_OWNERS) !== null
  return false
}

function isPlainKey(event: KeyboardEvent): boolean {
  return !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.altKey && !event.isComposing
}

/**
 * Keyboard shortcuts for the synced player, active while the workspace is
 * mounted: Space or K play/pause, Left/Right 5 s, J/L 10 s, `[` and `]`
 * previous/next segment. Keys typed into inputs, and keys a focused widget
 * uses itself (Space on a button, arrows in a tab list or a timeline lane),
 * are left alone. Handled keys never scroll the page.
 */
export function usePlayerShortcuts(segments: IntervalIndex<TimeRange> | null): void {
  const { clock } = useTimelineKit()
  const seek = useSeek()

  useEffect(() => {
    const run = (action: ShortcutAction): void => {
      if (action.type === 'toggle') return clock.toggle()
      if (action.type === 'step') return seek(clock.getTime() + action.deltaSec)
      const target = segments ? segmentJumpTarget(segments, clock.getTime(), action.direction) : null
      if (target !== null) seek(target)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      const action = isPlainKey(event) && !ownedByWidget(event) ? shortcutForKey(event.key) : null
      if (!action) return
      event.preventDefault()
      run(action)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [clock, seek, segments])
}
