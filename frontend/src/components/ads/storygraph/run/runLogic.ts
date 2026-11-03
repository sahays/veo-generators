/**
 * Pure async-run helpers (no React, no I/O): status transitions, poll schedule,
 * clock-skew-safe elapsed time, labels and terminal-state copy.
 */
import type { ProductionStatusResponse, RunProgress, RunView } from '@/types/runs'
import { PIPELINE_SUB_STAGES, classifyCascadeStop } from '../cascade/pipelineStages'

/** Poll cadence while a run is live (or just requested). */
export const ACTIVE_POLL_MS = 2500
/** Idle back-off: 15 s → 30 s → 60 s (then stays at 60 s). */
export const IDLE_BACKOFF_MS: readonly number[] = [15_000, 30_000, 60_000]
const MAX_ERROR_BACKOFF_MS = 30_000

/** Synchronous, pre-202 placeholder so the UI reacts on click. */
export interface StartingRun {
  label: string
  stage: string | null
  startedAtClient: number
}

/** What changed between two consecutive status reads (only emitted when something did). */
export interface RunTransition {
  /** A different run became active (also counts as a stage change). */
  started: RunView | null
  /** Active run moved to another stage (or started). Panels refresh the snapshot. */
  stageChanged: boolean
  /** A run finished since the previous read (`last_run` changed). */
  finished: RunView | null
}

const EXTRA_STAGE_LABELS: Record<string, string> = { S8_REPAIR: 'Shot repair', S8_PREVIZ: 'Blender previz' }

/**
 * Diff two status reads. `null` when nothing a panel cares about changed (progress ticks
 * and heartbeats are deliberately ignored so panels refresh only on stage change / completion).
 * The first read (`prev === null`) never emits: it is the baseline.
 */
export function diffRunTransition(
  prev: ProductionStatusResponse | null,
  next: ProductionStatusResponse,
): RunTransition | null {
  if (!prev) return null
  const a = prev.active_run
  const b = next.active_run
  const started = b && b.run_id !== a?.run_id ? b : null
  const stageChanged = !!b && (started !== null || b.stage !== a?.stage)
  const last = next.last_run
  const finished = last && last.run_id !== prev.last_run?.run_id ? last : null
  return started || stageChanged || finished ? { started, stageChanged, finished } : null
}

/** Delay before the next status poll. */
export function nextPollDelay(isLive: boolean, idleStreak: number, errorStreak: number): number {
  if (errorStreak > 0) return Math.min(ACTIVE_POLL_MS * 2 ** errorStreak, MAX_ERROR_BACKOFF_MS)
  if (isLive) return ACTIVE_POLL_MS
  const i = Math.min(Math.max(idleStreak - 1, 0), IDLE_BACKOFF_MS.length - 1)
  return IDLE_BACKOFF_MS[i]
}

/** server clock − client clock (ms) at the moment a status response was received. */
export function clockSkewMs(serverTimeIso: string, receivedAtClient: number): number {
  const server = Date.parse(serverTimeIso)
  return Number.isNaN(server) ? 0 : server - receivedAtClient
}

/** Elapsed ms of a server-timestamped run, corrected for clock skew; never negative. */
export function elapsedMs(startedAtIso: string, nowClient: number, skewMs: number): number {
  const started = Date.parse(startedAtIso)
  return Number.isNaN(started) ? 0 : Math.max(0, nowClient + skewMs - started)
}

/** `m:ss` under an hour, `h:mm:ss` above. */
export function formatElapsed(ms: number): string {
  const total = Math.floor(Math.max(0, ms) / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

/** Human label for a stage id (falls back to the id). */
export function stageLabel(stageId: string | null): string {
  if (!stageId) return ''
  return PIPELINE_SUB_STAGES.find((s) => s.id === stageId)?.label ?? EXTRA_STAGE_LABELS[stageId] ?? stageId
}

/** 0–100 for determinate progress, `null` for indeterminate. */
export function progressPercent(p: RunProgress | null): number | null {
  if (!p || p.total <= 0) return null
  return Math.min(100, Math.round((p.done / p.total) * 100))
}

/** Busy key compatible with the studio's `busyAction` (stage id, else `run:<kind>`). */
export function runBusyKey(active: RunView | null, starting: StartingRun | null): string | null {
  if (active) return active.stage ?? `run:${active.kind}`
  if (starting) return starting.stage ?? 'run:starting'
  return null
}

/** Planned-sequence position for multi-stage runs (`null` for single-stage runs). */
export function runSequencePosition(run: RunView | null): { index: number; total: number; label: string } | null {
  if (!run || run.stages.length < 2 || !run.stage) return null
  const index = run.stages.indexOf(run.stage) + 1
  return index > 0 ? { index, total: run.stages.length, label: stageLabel(run.stage) } : null
}

const CONFLICT_RE = /already in progress/i

/** True for the backend's 409 "A run is already in progress…" detail. */
export function isRunConflict(message: string): boolean {
  return CONFLICT_RE.test(message)
}

/**
 * Status of a run we are waiting on: `undefined` = still live, the finished `RunView`
 * when it is `last_run`, or `null` when it is neither (superseded / unknown).
 */
export function settledRun(runId: string, status: ProductionStatusResponse): RunView | null | undefined {
  if (status.active_run?.run_id === runId) return undefined
  return status.last_run?.run_id === runId ? status.last_run : null
}

export type TerminalTone = 'success' | 'warning' | 'destructive'

export interface TerminalCopy {
  tone: TerminalTone
  title: string
  message: string | null
  /** Stage to re-POST with `force=false` (interrupted runs only). */
  resumeStage: string | null
}

const isPipelineStage = (id: string | null): id is string => !!id && PIPELINE_SUB_STAGES.some((s) => s.id === id)

/** Readable copy for a finished run; paused runs reuse `classifyCascadeStop` semantics. */
export function terminalCopy(run: RunView): TerminalCopy {
  const label = stageLabel(run.stage) || run.label
  if (run.status === 'completed') return { tone: 'success', title: `${run.label} finished`, message: null, resumeStage: null }
  if (run.status === 'paused') {
    const graceful = run.error ? classifyCascadeStop(run.error, { label }) : null
    return { tone: 'warning', title: `${run.label} paused`, message: graceful ?? run.error, resumeStage: null }
  }
  if (run.status === 'interrupted') {
    const stage = run.stage ?? run.stages[0] ?? null
    const message = 'The worker stopped responding. Resume picks up where it left off; finished work is reused.'
    return { tone: 'warning', title: `${run.label} interrupted`, message, resumeStage: isPipelineStage(stage) ? stage : null }
  }
  return { tone: 'destructive', title: `${run.label} failed`, message: run.error, resumeStage: null }
}
