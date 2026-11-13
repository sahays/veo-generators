import type { TimeRange } from '@/types/insights'
import type { IntervalIndex } from './intervalIndex'

/** Seconds moved by the arrow keys. */
export const ARROW_STEP_SEC = 5
/** Seconds moved by J and L. */
export const JKL_STEP_SEC = 10
/** Pressing "previous" this soon after a segment starts goes to the one before it. */
const RESTART_GRACE_SEC = 0.75

export type ShortcutAction =
  | { type: 'toggle' }
  | { type: 'step'; deltaSec: number }
  | { type: 'segment'; direction: -1 | 1 }

const KEY_ACTIONS: Record<string, ShortcutAction> = {
  ' ': { type: 'toggle' },
  k: { type: 'toggle' },
  arrowleft: { type: 'step', deltaSec: -ARROW_STEP_SEC },
  arrowright: { type: 'step', deltaSec: ARROW_STEP_SEC },
  j: { type: 'step', deltaSec: -JKL_STEP_SEC },
  l: { type: 'step', deltaSec: JKL_STEP_SEC },
  '[': { type: 'segment', direction: -1 },
  ']': { type: 'segment', direction: 1 },
}

/** Player action for a `KeyboardEvent.key`, or null when the key is not a shortcut. */
export function shortcutForKey(key: string): ShortcutAction | null {
  return KEY_ACTIONS[key.toLowerCase()] ?? null
}

/**
 * Where "previous/next segment" lands from `timeSec`. Previous restarts the
 * current segment, or goes one further back when pressed right at its start.
 * Returns null when there is nowhere to go.
 */
export function segmentJumpTarget(
  segments: IntervalIndex<TimeRange>,
  timeSec: number,
  direction: -1 | 1,
): number | null {
  if (direction === 1) return segments.next(timeSec)?.start_sec ?? null
  const target = segments.previous(timeSec - RESTART_GRACE_SEC)
  return target ? target.start_sec : segments.size > 0 ? 0 : null
}

/** Shorten `text` to fit `widthPx` at roughly `charPx` per character; empty when nothing useful fits. */
export function fitLabel(text: string, widthPx: number, charPx = 6.2): string {
  const maxChars = Math.floor(widthPx / charPx)
  if (maxChars >= text.length) return text
  return maxChars < 3 ? '' : `${text.slice(0, maxChars - 1).trimEnd()}…`
}
