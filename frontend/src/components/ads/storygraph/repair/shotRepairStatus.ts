import type { BadgeProps } from '@/components/ui/badge'
import { MAX_SHOT_REPAIR_ATTEMPTS, type BlockingShot } from '@/types/storygraph'

export type ShotChipKind = 'failed' | 'repairing' | 'manual' | 'outdated'

interface ShotChip {
  kind: ShotChipKind
  label: string
  variant: NonNullable<BadgeProps['variant']>
}

const CHIPS: Record<ShotChipKind, ShotChip> = {
  failed: { kind: 'failed', label: 'Failed', variant: 'destructive' },
  repairing: { kind: 'repairing', label: 'Repairing', variant: 'indigo' },
  manual: { kind: 'manual', label: 'Needs your edit', variant: 'warning' },
  outdated: { kind: 'outdated', label: 'Outdated', variant: 'default' },
}

const MAX_VISIBLE_REASONS = 3

/** Shot ids eligible for automatic repair (blocking and not yet flagged for a human edit). */
export function autoRepairableShotIds(blocking: BlockingShot[]): string[] {
  return blocking.filter((s) => !s.needs_manual_edit).map((s) => s.shot_id)
}

/**
 * Status chip for a blocking shot. A shot is "Repairing" while a bulk repair runs
 * (unless it is already flagged for manual edit) or while it is being regenerated.
 */
export function deriveShotChip(shot: BlockingShot, isBulkRepairing: boolean, regeneratingShotId: string | null): ShotChip {
  if (regeneratingShotId === shot.shot_id) return CHIPS.repairing
  if (shot.needs_manual_edit) return CHIPS.manual
  if (isBulkRepairing) return CHIPS.repairing
  return shot.latest_status === 'outdated' ? CHIPS.outdated : CHIPS.failed
}

/** Deduplicated, capped reasons for a row; manual-edit reasons take precedence. */
export function conciseReasons(shot: BlockingShot): { visible: string[]; hidden: number } {
  const source = shot.needs_manual_edit && shot.manual_edit_reasons.length > 0
    ? shot.manual_edit_reasons
    : [...shot.failure_reasons, ...shot.artifact_flags]
  const unique = [...new Set(source.filter((r) => r.trim().length > 0))]
  return { visible: unique.slice(0, MAX_VISIBLE_REASONS), hidden: Math.max(0, unique.length - MAX_VISIBLE_REASONS) }
}

export const attemptsLabel = (shot: BlockingShot): string =>
  `${Math.min(shot.repair_attempts ?? 0, MAX_SHOT_REPAIR_ATTEMPTS)}/${MAX_SHOT_REPAIR_ATTEMPTS} attempts`
