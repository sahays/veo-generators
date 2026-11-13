import { useState } from 'react'
import { AlertTriangle, Check, Loader2, RotateCcw } from 'lucide-react'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { ProgressBar } from '@/components/shared/media/ProgressBar'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/useAuthStore'

/** One stage of a staged worker job, in the order the worker runs them. */
export interface JobStage {
  /** The record's `stage` value while the job is in this stage. */
  key: string
  label: string
  /** Shown under the label unless the stage is current and the record has a `stage_detail`. */
  hint: string
}

type StepState = 'done' | 'active' | 'failed' | 'waiting'

function stepState(index: number, activeIndex: number, failed: boolean): StepState {
  if (index < activeIndex) return 'done'
  if (index > activeIndex) return 'waiting'
  return failed ? 'failed' : 'active'
}

const STEP_STYLES: Record<StepState, string> = {
  done: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  active: 'border-accent/50 bg-accent/10 text-accent-dark',
  failed: 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400',
  waiting: 'border-border bg-muted/40 text-muted-foreground',
}

function StepIcon({ state, index }: { state: StepState; index: number }): JSX.Element {
  if (state === 'done') return <Check size={14} aria-hidden />
  if (state === 'active') return <Loader2 size={14} aria-hidden className="animate-spin motion-reduce:animate-none" />
  if (state === 'failed') return <AlertTriangle size={14} aria-hidden />
  return <span aria-hidden className="text-[11px] font-bold">{index + 1}</span>
}

interface StageStepProps {
  stage: JobStage
  index: number
  state: StepState
  detail: string
}

function StageStep({ stage, index, state, detail }: StageStepProps): JSX.Element {
  const current = state === 'active' || state === 'failed'
  return (
    <li aria-current={current ? 'step' : undefined} data-state={state} data-stage={stage.key} className="flex min-w-0 flex-1 items-start gap-2.5">
      <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full border', STEP_STYLES[state])}>
        <StepIcon state={state} index={index} />
      </span>
      <span className="min-w-0">
        <span className={cn('block text-xs font-semibold', state === 'waiting' ? 'text-muted-foreground' : 'text-foreground')}>
          {stage.label}
          <span className="sr-only"> ({state})</span>
        </span>
        <span className="block text-[11px] leading-snug text-muted-foreground">{current && detail ? detail : stage.hint}</span>
      </span>
    </li>
  )
}

export interface JobProgressProps {
  /** Accessible name of the section, e.g. "Analysis progress". */
  ariaLabel: string
  stages: readonly JobStage[]
  /** The record's `stage`. Anything that is not a stage key means the job is still queued. */
  activeStage: string
  failed: boolean
  /** The record's `stage_detail`, shown on the current stage. */
  detail?: string
  progressPct: number
  /** Appended to the status line, e.g. " · 3 windows". */
  statusExtra?: string
  /** Replaces the status line ("N% complete"), e.g. while the job waits on something else. */
  statusText?: string
  /** Shown under the status line: the retry panel when failed, or a note. */
  children?: React.ReactNode
}

/** Stage stepper with a progress bar and a polite status line, for a record whose worker job is running or failed. */
export function JobProgress({ ariaLabel, stages, activeStage, failed, detail = '', progressPct, statusExtra = '', statusText, children }: JobProgressProps): JSX.Element {
  const activeIndex = stages.findIndex((stage) => stage.key === activeStage)
  const percent = Math.min(Math.max(progressPct, 0), 100)
  return (
    <section aria-label={ariaLabel} data-testid="processing-view" className="space-y-5 rounded-xl border border-border bg-card p-5">
      <ol className="flex flex-col gap-4 md:flex-row">
        {stages.map((stage, index) => (
          <StageStep key={stage.key} stage={stage} index={index} state={stepState(index, activeIndex, failed)} detail={detail} />
        ))}
      </ol>
      {!failed && <ProgressBar progress={percent} showSpinner={false} />}
      {!failed && (
        <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
          {statusText ?? (activeIndex < 0 ? 'Waiting for a worker to pick this up…' : `${Math.round(percent)}% complete`)}
          {statusExtra}
        </p>
      )}
      {children}
    </section>
  )
}

export interface JobRetryPanelProps {
  /** The record's `error_message`. */
  error: string
  retryLabel: string
  /** Sends the retry request. */
  onRetry: () => Promise<unknown>
  /** Called after the retry request succeeded, so the page can start polling again. */
  onRetried: () => void
  /** A line under the button, e.g. what a retry reuses. */
  hint?: string
}

/** Error of a failed job with a retry button (for users who may write). */
export function JobRetryPanel({ error, retryLabel, onRetry, onRetried, hint }: JobRetryPanelProps): JSX.Element {
  const canWrite = useAuthStore((state) => state.isMaster || state.isPower)
  const [retrying, setRetrying] = useState(false)
  const [retryError, setRetryError] = useState<string | null>(null)
  const retry = async (): Promise<void> => {
    setRetrying(true)
    setRetryError(null)
    try {
      await onRetry()
      onRetried()
    } catch (cause: unknown) {
      setRetryError(cause instanceof Error ? cause.message : 'Retry failed')
      setRetrying(false)
    }
  }
  return (
    <div role="alert" className="space-y-3">
      <ErrorDisplay error={error} size="md" />
      <ErrorDisplay error={retryError} />
      {canWrite && (
        <Button icon={retrying ? Loader2 : RotateCcw} onClick={retry} disabled={retrying} className={cn(retrying && '[&_svg]:animate-spin')}>
          {retrying ? 'Retrying…' : retryLabel}
        </Button>
      )}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}
