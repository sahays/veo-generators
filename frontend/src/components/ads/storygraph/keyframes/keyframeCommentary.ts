/** Pure formatters turning raw keyframe fields into readable commentary (no React, no I/O). */

/** One entity's state at a second: who, what they are doing, what they hold. */
export interface EntityLine {
  who: string
  action: string
  holding: string[]
}

const HOLDING_RE = /\s*\(holding ([^)]*)\)\s*$/

const capitalize = (s: string): string => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)

function parseEntity(part: string): EntityLine | null {
  const text = part.trim()
  if (!text) return null
  const held = HOLDING_RE.exec(text)
  const body = held ? text.slice(0, held.index) : text
  const holding = held ? held[1].split(',').map((h) => h.trim()).filter(Boolean) : []
  const sep = body.indexOf(': ')
  if (sep <= 0) return { who: '', action: capitalize(body.trim()), holding }
  return { who: body.slice(0, sep).trim(), action: capitalize(body.slice(sep + 2).trim()), holding }
}

/**
 * Splits the backend `state_summary` blob — `"Ava: pose (holding a, b); Ben: pose"` — into
 * per-entity lines. Only the first `": "` separates the name, so poses may contain colons.
 */
export function parseStateSummary(summary: string): EntityLine[] {
  return summary.split(';').map(parseEntity).filter((l): l is EntityLine => l !== null)
}

const DRIFT_LABEL: Record<string, string> = {
  bad_fraction: 'off-plate',
  chroma_ratio: 'chroma',
  contrast_ratio: 'contrast',
}

/** Compact drift meta, e.g. `off-plate 3.1% · chroma 0.98 · contrast 1.02`; `''` when absent. */
export function formatDrift(drift: Record<string, number>): string {
  return Object.entries(drift)
    .filter(([, v]) => Number.isFinite(v))
    .map(([k, v]) => {
      const label = DRIFT_LABEL[k] ?? k.replace(/_/g, ' ')
      return k.endsWith('fraction') ? `${label} ${(v * 100).toFixed(1)}%` : `${label} ${v.toFixed(2)}`
    })
    .join(' · ')
}

/** Long enough to clamp to 3 lines behind a "more" toggle. */
export function isLongCommentary(lines: EntityLine[]): boolean {
  const chars = lines.reduce((n, l) => n + l.who.length + l.action.length + l.holding.join(', ').length, 0)
  return lines.length > 3 || chars > 220
}
