import { useEffect, useState } from 'react'
import type { RunProgress } from '@/types/runs'
import { cn } from '@/lib/utils'
import { formatElapsed, progressPercent } from './runLogic'

/** Determinate bar when progress is known, otherwise an indeterminate sweep (fixed height: no layout shift). */
export const RunProgressTrack = ({ progress, label, tone = 'accent' }: { progress: RunProgress | null; label: string; tone?: 'accent' | 'success' }) => {
  const pct = progressPercent(progress)
  const valueText = progress ? `${progress.done} of ${progress.total} ${progress.unit}` : 'In progress'
  return (
    <div
      role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined} aria-valuetext={valueText}
      className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted"
    >
      <div
        className={cn('absolute inset-y-0 rounded-full', tone === 'success' ? 'bg-emerald-500' : 'bg-accent', pct === null ? 'animate-progress-indeterminate' : 'left-0 transition-[width] duration-500')}
        style={pct === null ? undefined : { width: `${pct}%` }}
      />
    </div>
  )
}

/** Locally ticking elapsed clock (1 s); isolated so only this text re-renders each second. */
export const ElapsedClock = ({ since, skewMs }: { since: number; skewMs: number }) => {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground" aria-hidden>{formatElapsed(now + skewMs - since)}</span>
}
