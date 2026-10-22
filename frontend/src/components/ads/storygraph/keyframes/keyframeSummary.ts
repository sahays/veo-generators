/** Pure helpers for the S8_KEYFRAMES strip UI (no React, no I/O). */
import type { KeyframeFrameStatus, KeyframeStripResponse } from '@/types/keyframes'
import type { StoryGraphStageRun } from '@/types/project'
import { KEYFRAMES_STAGE } from '../cascade/pipelineStages'

export type BadgeTone = 'success' | 'warning' | 'destructive'

export const FRAME_STATUS_META: Record<KeyframeFrameStatus, { label: string; tone: BadgeTone }> = {
  approved: { label: 'Approved', tone: 'success' },
  needs_review: { label: 'Needs review', tone: 'warning' },
  manual_edit: { label: 'Manual edit', tone: 'destructive' },
}

export interface StripSummary {
  total: number
  needsReview: number
  manualEdit: number
  sharedStart: boolean
  label: string
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

/** Single pass over the frames: counts + compact human label for the collapsed row. */
export function summarizeStrip(strip: KeyframeStripResponse): StripSummary {
  let needsReview = 0
  let manualEdit = 0
  for (const f of strip.frames) {
    if (f.status === 'needs_review') needsReview += 1
    else if (f.status === 'manual_edit') manualEdit += 1
  }
  const sharedStart = strip.frames.some((f) => f.t === 0 && f.shared_from !== null)
  const parts = [plural(strip.frames.length, 'keyframe')]
  if (needsReview > 0) parts.push(`${needsReview} need${needsReview === 1 ? 's' : ''} review`)
  if (manualEdit > 0) parts.push(`${manualEdit} manual edit`)
  if (sharedStart) parts.push('shared start')
  return { total: strip.frames.length, needsReview, manualEdit, sharedStart, label: parts.join(' · ') }
}

/** Parse `"<shot_id>@t<N>"` into its parts; `null` for malformed / absent refs. */
export function parseSharedFrom(ref: string | null): { shotId: string; t: number } | null {
  const m = ref ? /^(.+)@t(\d+)$/.exec(ref) : null
  return m ? { shotId: m[1], t: Number(m[2]) } : null
}

/** Highest t in the strip (N), or -1 for an empty strip. */
export function lastFrameT(strip: KeyframeStripResponse): number {
  return strip.frames.reduce((max, f) => (f.t > max ? f.t : max), -1)
}

/**
 * shot_id → next clip's shot_id, built in O(n). A strip whose frame 0 is shared from
 * `<prev>@tN` is authoritative; otherwise fall back to (scene_id, clip_index + 1).
 */
export function buildSuccessorIndex(strips: KeyframeStripResponse[]): Record<string, string> {
  const byClip: Record<string, string> = {}
  for (const s of strips) byClip[`${s.scene_id}#${s.clip_index}`] = s.shot_id
  const next: Record<string, string> = {}
  for (const s of strips) {
    const fallback = byClip[`${s.scene_id}#${s.clip_index + 1}`]
    if (fallback && !(s.shot_id in next)) next[s.shot_id] = fallback
  }
  for (const s of strips) {
    const shared = parseSharedFrom(s.frames.find((f) => f.t === 0)?.shared_from ?? null)
    if (shared) next[shared.shotId] = s.shot_id
  }
  return next
}

/** Plain-language consequences of regenerating frame `t` (shown before confirming). */
export function regenerateImpact(strip: KeyframeStripResponse, t: number, nextShotId: string | null): string[] {
  const n = lastFrameT(strip)
  const range = t >= n ? `frame t${t}` : `frames t${t}–t${n}`
  const lines = [
    `Re-derives ${range} of ${strip.shot_id} as a new keyframe set (v${strip.version + 1}); earlier frames are kept.`,
    `Marks the ${strip.shot_id} clip render stale — it re-renders on the next S8 render.`,
  ]
  if (nextShotId) {
    lines.push(`t${n} is the shared start of ${nextShotId}: it and the later clips of scene ${strip.scene_id} re-derive, and their renders go stale too.`)
  }
  return lines
}

/** Re-fetch key for the board: changes whenever an S8_KEYFRAMES run starts/finishes. */
export function keyframeRefreshKey(stageRuns: StoryGraphStageRun[], pipelineStatus?: string): string {
  const runs = stageRuns
    .filter((r) => r.stage === KEYFRAMES_STAGE)
    .map((r) => `${r.id ?? r.created_at ?? ''}:${r.status ?? ''}:${r.completed ? 1 : 0}`)
  return `${pipelineStatus ?? ''}|${runs.join(',')}`
}
