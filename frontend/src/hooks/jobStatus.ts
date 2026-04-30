/**
 * Shared types/defaults for job-status pills used by WorkPage components.
 *
 * Each feature still owns its in-progress labels (the wording differs:
 * "Stitching promo together..." vs "Reframing video..."), but the terminal
 * `completed` / `failed` rows and the type live here so they don't drift.
 */

export interface JobStatus {
  label: string
  color: string
}

export type JobStatusConfig = Record<string, JobStatus>

export const TERMINAL_STATUS_CONFIG: JobStatusConfig = {
  completed: { label: 'Complete', color: 'text-emerald-500' },
  failed: { label: 'Failed', color: 'text-red-500' },
}

/** Combine feature-specific in-progress rows with the universal terminal
 * defaults; pass `overrides` to retitle the terminal rows for a feature. */
export const buildStatusConfig = (
  inProgress: JobStatusConfig,
  overrides: JobStatusConfig = {},
): JobStatusConfig => ({
  ...TERMINAL_STATUS_CONFIG,
  ...inProgress,
  ...overrides,
})
