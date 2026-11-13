import { ArrowDownRight, ArrowUpRight, FileQuestion, FlaskConical, Minus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { SIMULATED_LABEL, describeDelta, formatDelta } from '@/types/engagement/reportFormat'

export interface DeltaBadgeProps {
  /** Percent above (+) or below (−) the overall average. */
  pct: number
  className?: string
}

/** A figure's distance from the average. Direction is shown by an arrow and a sign as well as by colour. */
export function DeltaBadge({ pct, className }: DeltaBadgeProps): JSX.Element {
  const rounded = Math.round(pct * 10) / 10
  const Icon = rounded > 0 ? ArrowUpRight : rounded < 0 ? ArrowDownRight : Minus
  const variant = rounded > 0 ? 'success' : rounded < 0 ? 'destructive' : 'default'
  return (
    <Badge variant={variant} className={cn('font-mono tabular-nums', className)} title={describeDelta(pct)}>
      <Icon size={10} aria-hidden />
      <span aria-hidden>{formatDelta(pct)}</span>
      <span className="sr-only">{describeDelta(pct)}</span>
    </Badge>
  )
}

/**
 * Shown wherever numbers derived from a template curve appear: the curve is
 * illustrative, so nothing on the tab describes real viewers.
 */
export function SimulatedNote(): JSX.Element {
  return (
    <p role="note" data-testid="simulated-note" className="flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs leading-snug text-amber-800 dark:text-amber-300">
      <FlaskConical size={14} aria-hidden className="mt-0.5 shrink-0" />
      <span>
        <strong className="font-semibold">{SIMULATED_LABEL}.</strong> This curve is an illustrative template, not audience measurement. Everything on this tab shows how the video lines up with that template, not how viewers behaved.
      </span>
    </p>
  )
}

export interface EmptyProseProps {
  title: string
  children: React.ReactNode
  className?: string
}

/** Stands in for text the language-model step did not produce, so a missing explanation never looks like a blank card. */
export function EmptyProse({ title, children, className }: EmptyProseProps): JSX.Element {
  return (
    <div data-testid="empty-prose" className={cn('flex items-start gap-2.5 rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2.5 text-xs text-muted-foreground', className)}>
      <FileQuestion size={15} aria-hidden className="mt-0.5 shrink-0" />
      <p className="leading-snug">
        <span className="font-semibold text-foreground">{title}</span> {children}
      </p>
    </div>
  )
}
