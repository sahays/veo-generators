import type { StoryGraphAsset, StoryGraphData, StoryGraphEntity } from '@/types/project'

/** Every entity (the lean snapshot ships only the three groups; legacy ones also had `all`). */
export function allEntities(sg: StoryGraphData | undefined): StoryGraphEntity[] {
  const ents = sg?.entities
  if (!ents) return []
  return ents.all ?? [...(ents.characters || []), ...(ents.locations || []), ...(ents.objects || [])]
}

/** Asset index over run-only assets plus those embedded under appearances (deduped server-side). */
export function indexAssets(sg: StoryGraphData | undefined): Record<string, StoryGraphAsset> {
  const out: Record<string, StoryGraphAsset> = {}
  for (const app of sg?.appearances || []) for (const a of app.assets || []) out[a.id] = a
  for (const a of sg?.assets || []) out[a.id] = a
  return out
}

/** Total render attempts across all shots (snapshot returns only the active run per shot). */
export function generationRunsTotal(sg: StoryGraphData | undefined): number {
  return sg?.generation_runs_total ?? (sg?.generation_runs || []).length
}

const AUXILIARY_KINDS = ['composite_sheet', 'first_frame'] as const

/** Count of composite sheets + first frames, from server-side counts when present. */
export function auxiliaryAssetCount(sg: StoryGraphData | undefined): number {
  const counts = sg?.asset_counts
  if (counts) return AUXILIARY_KINDS.reduce((n, k) => n + (counts[k] || 0), 0)
  return (sg?.assets || []).filter((a) => (AUXILIARY_KINDS as readonly string[]).includes(a.kind)).length
}
