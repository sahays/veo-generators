/**
 * Framework-free status poller for one production's async runs.
 *
 * - polls `GET /status` every 2.5 s while a run is live (or just requested), backs off
 *   15 s → 30 s → 60 s when idle, pauses while the tab is hidden and re-polls on return;
 * - never overlaps polls (a request made while one is in flight is coalesced);
 * - exposes an immutable snapshot for `useSyncExternalStore` that only changes when
 *   something visible changed (heartbeat-only ticks do not re-render);
 * - emits stage-change / completion transitions and resolves `waitFor(runId)` promises.
 */
import type { ProductionStatusResponse, RunAccepted, RunView } from '@/types/runs'
import {
  clockSkewMs, diffRunTransition, isRunConflict, nextPollDelay, settledRun,
  type RunTransition, type StartingRun,
} from './runLogic'

export interface RunNotice { kind: 'conflict' | 'error'; message: string }

export interface RunSnapshot {
  status: ProductionStatusResponse | null
  skewMs: number
  starting: StartingRun | null
  notice: RunNotice | null
  /** Finished run observed live (or an interrupted run found on load); cleared on dismiss. */
  terminal: RunView | null
}

export type StartResult =
  | { ok: true; run: RunView }
  | { ok: false; conflict: boolean; error: string }

type StatusFetcher = (pid: string) => Promise<ProductionStatusResponse>
interface Waiter { runId: string; afterSeq: number; resolve: (run: RunView | null) => void }

const EMPTY: RunSnapshot = { status: null, skewMs: 0, starting: null, notice: null, terminal: null }

/** Fields whose change is user-visible; heartbeat_at / server_time are excluded on purpose. */
function fingerprint(s: ProductionStatusResponse): string {
  const a = s.active_run
  const p = a?.progress
  return [s.pipeline_status, a?.run_id, a?.status, a?.stage, p?.done, p?.total, p?.current, s.last_run?.run_id, s.last_run?.status].join('|')
}

const errorText = (err: unknown): string => (err instanceof Error ? err.message : String(err))

export class RunPoller {
  private snap: RunSnapshot = EMPTY
  private readonly storeListeners = new Set<() => void>()
  private readonly transitionListeners = new Set<(t: RunTransition) => void>()
  private waiters: Waiter[] = []
  private timer: ReturnType<typeof setTimeout> | null = null
  private inFlight = false
  private queued = false
  private running = false
  private seq = 0
  private minSeq = 0
  private idleStreak = 0
  private errorStreak = 0
  private lastPrint = ''
  /** True between a run POST and its response: polls must not clear the optimistic state. */
  private awaitingAccept = false
  private readyResolvers: Array<() => void> = []

  constructor(readonly productionId: string, private readonly fetchStatus: StatusFetcher) {}

  readonly subscribe = (listener: () => void): (() => void) => {
    this.storeListeners.add(listener)
    return () => this.storeListeners.delete(listener)
  }

  readonly getSnapshot = (): RunSnapshot => this.snap

  onTransition(listener: (t: RunTransition) => void): () => void {
    this.transitionListeners.add(listener)
    return () => this.transitionListeners.delete(listener)
  }

  isLocked(): boolean {
    return this.snap.starting !== null || this.snap.status?.active_run != null
  }

  start(): void {
    if (this.running) return
    this.running = true
    document.addEventListener('visibilitychange', this.onVisibility)
    this.pollNow()
  }

  stop(): void {
    this.running = false
    this.clearTimer()
    document.removeEventListener('visibilitychange', this.onVisibility)
    this.waiters.forEach((w) => w.resolve(null))
    this.waiters = []
  }

  /** Poll immediately (coalesced with an in-flight poll) and reset the idle back-off. */
  readonly pollNow = (): void => {
    this.idleStreak = 0
    if (this.inFlight) { this.queued = true; return }
    if (!this.running || document.hidden) return
    this.clearTimer()
    void this.poll()
  }

  /** Resolves once the first status read has been applied. */
  ready(): Promise<void> {
    if (this.snap.status) return Promise.resolve()
    return new Promise((resolve) => this.readyResolvers.push(resolve))
  }

  /** Resolves with the finished run (or `null` if it vanished / the poller stopped). */
  waitFor(runId: string): Promise<RunView | null> {
    return new Promise((resolve) => this.waiters.push({ runId, afterSeq: this.seq, resolve }))
  }

  dismissTerminal(): void {
    this.set({ terminal: null, notice: null })
  }

  reportError(message: string): void {
    this.set({ notice: { kind: 'error', message } })
  }

  /**
   * Start a run: the optimistic `starting` state is published synchronously (before the 202),
   * a 409 surfaces the server message and re-syncs to the active run.
   */
  async run(label: string, stage: string | null, call: () => Promise<RunAccepted>): Promise<StartResult> {
    if (this.isLocked()) return { ok: false, conflict: true, error: `A run is in progress: ${this.lockLabel()}` }
    this.awaitingAccept = true
    this.set({ starting: { label, stage, startedAtClient: Date.now() }, notice: null, terminal: null })
    try {
      const accepted = await call()
      this.acceptRun(accepted.run)
      return { ok: true, run: accepted.run }
    } catch (err) {
      const message = errorText(err)
      const conflict = isRunConflict(message)
      this.awaitingAccept = false
      this.set({ starting: null, notice: { kind: conflict ? 'conflict' : 'error', message } })
      this.pollNow()
      return { ok: false, conflict, error: message }
    }
  }

  lockLabel(): string {
    return this.snap.status?.active_run?.label ?? this.snap.starting?.label ?? ''
  }

  private acceptRun(run: RunView): void {
    this.awaitingAccept = false
    this.minSeq = this.seq // drop polls that were already in flight before the 202
    const status = this.snap.status
    if (status) this.set({ starting: null, status: { ...status, active_run: run } })
    this.pollNow()
  }

  private async poll(): Promise<void> {
    this.inFlight = true
    const seq = ++this.seq
    try {
      const next = await this.fetchStatus(this.productionId)
      this.errorStreak = 0
      if (seq > this.minSeq) this.apply(next, seq, Date.now())
    } catch {
      this.errorStreak += 1
    } finally {
      this.inFlight = false
      this.scheduleNext()
    }
  }

  private apply(next: ProductionStatusResponse, seq: number, receivedAt: number): void {
    const prev = this.snap.status
    const transition = diffRunTransition(prev, next)
    this.idleStreak = next.active_run ? 0 : this.idleStreak + 1
    const changed = fingerprint(next) !== this.lastPrint || this.snap.starting !== null || !prev
    this.lastPrint = fingerprint(next)
    const starting = this.awaitingAccept ? this.snap.starting : null
    if (changed) this.set({ status: next, skewMs: clockSkewMs(next.server_time, receivedAt), starting, terminal: this.terminalFor(prev, next, transition) })
    this.resolveWaiters(next, seq)
    if (!prev) this.flushReady()
    if (transition) this.transitionListeners.forEach((l) => l(transition))
  }

  private terminalFor(prev: ProductionStatusResponse | null, next: ProductionStatusResponse, t: RunTransition | null): RunView | null {
    if (t?.finished) return t.finished
    if (!prev && next.last_run?.status === 'interrupted' && !next.active_run) return next.last_run
    return next.active_run ? null : this.snap.terminal
  }

  private resolveWaiters(status: ProductionStatusResponse, seq: number): void {
    this.waiters = this.waiters.filter((w) => {
      if (seq <= w.afterSeq) return true
      const settled = settledRun(w.runId, status)
      if (settled === undefined) return true
      w.resolve(settled)
      return false
    })
  }

  private flushReady(): void {
    this.readyResolvers.forEach((r) => r())
    this.readyResolvers = []
  }

  private scheduleNext(): void {
    if (!this.running) return
    if (this.queued) { this.queued = false; this.pollNow(); return }
    if (document.hidden) return
    this.timer = setTimeout(() => void this.poll(), nextPollDelay(this.isLocked(), this.idleStreak, this.errorStreak))
  }

  private readonly onVisibility = (): void => {
    if (document.hidden) this.clearTimer()
    else this.pollNow()
  }

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }

  private set(patch: Partial<RunSnapshot>): void {
    this.snap = { ...this.snap, ...patch }
    this.storeListeners.forEach((l) => l())
  }
}
