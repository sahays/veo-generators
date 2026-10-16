/**
 * Shared types, status badge styles/labels, and helpers for job-status pills
 * used by LandingPage cards and WorkPage components.
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

export const buildStatusConfig = (
  inProgress: JobStatusConfig,
  overrides: JobStatusConfig = {},
): JobStatusConfig => ({
  ...TERMINAL_STATUS_CONFIG,
  ...inProgress,
  ...overrides,
})

export const UNIFIED_STATUS_STYLES: Record<string, string> = {
  pending: 'text-slate-600 dark:text-slate-400 bg-slate-500/12 border border-slate-500/20',
  draft: 'text-muted-foreground bg-muted border border-border',
  analyzing: 'text-amber-600 dark:text-amber-400 bg-amber-500/12 border border-amber-500/20',
  scripted: 'text-indigo-600 dark:text-indigo-400 bg-indigo-500/12 border border-indigo-500/20',
  generating: 'text-amber-600 dark:text-amber-400 bg-amber-500/12 border border-amber-500/20',
  processing: 'text-blue-600 dark:text-blue-400 bg-blue-500/12 border border-blue-500/20',
  extracting: 'text-blue-600 dark:text-blue-400 bg-blue-500/12 border border-blue-500/20',
  stitching: 'text-indigo-600 dark:text-indigo-400 bg-indigo-500/12 border border-indigo-500/20',
  encoding: 'text-purple-600 dark:text-purple-400 bg-purple-500/12 border border-purple-500/20',
  screenshots_ready: 'text-blue-600 dark:text-blue-400 bg-blue-500/12 border border-blue-500/20',
  partial: 'text-orange-600 dark:text-orange-400 bg-orange-500/12 border border-orange-500/20',
  completed: 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/12 border border-emerald-500/20',
  failed: 'text-red-600 dark:text-red-400 bg-red-500/12 border border-red-500/20',
}

export const UNIFIED_STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  draft: 'Draft',
  analyzing: 'Analyzing',
  scripted: 'Scripted',
  generating: 'Generating',
  processing: 'Processing',
  extracting: 'Extracting',
  stitching: 'Stitching',
  encoding: 'Encoding',
  screenshots_ready: 'Ready',
  partial: 'Partial',
  completed: 'Completed',
  failed: 'Failed',
}

export function formatElapsedDuration(
  createdAt?: string,
  completedAt?: string,
): string | null {
  if (!createdAt || !completedAt) return null
  const ms = new Date(completedAt).getTime() - new Date(createdAt).getTime()
  const secs = Math.round(ms / 1000)
  if (secs <= 0) return null
  return secs < 60 ? `${secs}s` : `${Math.round(secs / 60)}m`
}
