/** Pure view-model helpers for the Blender previz board (no React, no I/O). */
import type {
  PrevizJobStatus,
  PrevizRestyleVariant,
  PrevizRunVariant,
  PrevizStageStatus,
  PrevizVariant,
  ShotPreviz,
} from '@/types/previz'

export type PrevizTone = 'default' | 'accent' | 'success' | 'warning' | 'destructive'

export const RESTYLE_VARIANTS: readonly PrevizRestyleVariant[] = ['E1_omni_restyle', 'E2_keyframe_restyle']

export const VARIANT_LABEL: Record<PrevizRestyleVariant, string> = {
  E1_omni_restyle: 'Omni restyle (E1)',
  E2_keyframe_restyle: 'Keyframe restyle (E2)',
}

export const RUN_VARIANT_OPTIONS: { value: PrevizRunVariant; label: string; description: string }[] = [
  { value: 'previz_only', label: 'Previz only', description: 'Blender greybox renders, no AI restyle' },
  { value: 'E1_omni_restyle', label: 'Omni restyle (E1)', description: 'Greybox + Omni video-to-video restyle' },
  { value: 'E2_keyframe_restyle', label: 'Keyframe restyle (E2)', description: 'Greybox + restyled keyframes animated by Veo' },
  { value: 'both', label: 'Both', description: 'Greybox + E1 and E2 side by side' },
]

export const JOB_STATUS_META: Record<PrevizJobStatus, { label: string; tone: PrevizTone }> = {
  pending: { label: 'Pending', tone: 'default' },
  running: { label: 'Rendering', tone: 'accent' },
  done: { label: 'Done', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
}

export const STAGE_STATUS_META: Record<PrevizStageStatus, { label: string; tone: PrevizTone }> = {
  idle: { label: 'Idle', tone: 'default' },
  running: { label: 'Running', tone: 'accent' },
  approved: { label: 'Approved', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
}

export interface PrevizSceneGroup {
  sceneId: string
  label: string
  shots: ShotPreviz[]
}

export interface SceneRef {
  id: string
  index: number
  heading?: string
}

function sceneLabel(ref: SceneRef | undefined, sceneId: string): string {
  if (!ref) return sceneId
  return ref.heading ? `Scene ${ref.index + 1} · ${ref.heading}` : `Scene ${ref.index + 1}`
}

/**
 * Groups shots by scene in O(n log n): scenes follow storyboard order (unknown scenes last,
 * in first-seen order); shots inside a scene follow `clip_index`.
 */
export function groupShotsByScene(shots: ShotPreviz[], scenes: SceneRef[]): PrevizSceneGroup[] {
  const refs = new Map(scenes.map((s) => [s.id, s]))
  const buckets = new Map<string, ShotPreviz[]>()
  for (const shot of shots) {
    const bucket = buckets.get(shot.scene_id)
    if (bucket) bucket.push(shot)
    else buckets.set(shot.scene_id, [shot])
  }
  const firstSeen = [...buckets.keys()]
  const seenAt = new Map(firstSeen.map((id, i) => [id, i]))
  const order = (id: string): number => refs.get(id)?.index ?? scenes.length + (seenAt.get(id) ?? 0)
  return firstSeen
    .sort((a, b) => order(a) - order(b))
    .map((sceneId) => ({
      sceneId,
      label: sceneLabel(refs.get(sceneId), sceneId),
      shots: [...(buckets.get(sceneId) ?? [])].sort((a, b) => a.clip_index - b.clip_index),
    }))
}

/** O(1) variant lookup for one shot. */
export function variantsByKind(shot: ShotPreviz): Partial<Record<PrevizRestyleVariant, PrevizVariant>> {
  return Object.fromEntries(shot.variants.map((v) => [v.variant, v]))
}

/** Plain-language cost note for the run confirmation dialog. */
export function runCostLines(variant: PrevizRunVariant, sceneCount: number | null, force: boolean): string[] {
  const scope = sceneCount === null ? 'every scene' : `${sceneCount} selected scene${sceneCount === 1 ? '' : 's'}`
  const lines = [`Renders a Blender greybox previz for each shot in ${scope} (CPU render time, no model cost).`]
  if (variant === 'E1_omni_restyle' || variant === 'both') lines.push('E1 sends every greybox clip through Omni video-to-video restyle (billed per output second).')
  if (variant === 'E2_keyframe_restyle' || variant === 'both') lines.push('E2 restyles keyframes with image generation, then animates them with Veo (billed per image and per video second).')
  lines.push(force ? 'Force is on: existing renders are discarded and re-rendered.' : 'Shots that already have a finished render are skipped.')
  return lines
}
