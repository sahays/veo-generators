import type { ReactNode } from 'react'
import { AlertTriangle, Check, Loader2, Eye } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Disclosure } from '@/components/ui/disclosure'
import type { ActiveStepId, MacroStepCardDef } from '../storyGraphStudioTypes'
import type { StepState } from './studioStatus'

export interface StepAccordionItem {
  card: MacroStepCardDef
  state: StepState
}

export interface StudioStepAccordionProps {
  items: StepAccordionItem[]
  isExpanded: (id: ActiveStepId) => boolean
  onToggle: (id: ActiveStepId, open: boolean) => void
  renderStep: (id: ActiveStepId) => ReactNode
}

const STATE_LABEL: Record<StepState, string> = {
  done: 'Done', running: 'Running', failed: 'Failed', attention: 'Needs review', pending: 'Not started',
}

const STATE_STYLE: Record<StepState, string> = {
  done: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  running: 'bg-accent/20 text-accent-dark',
  failed: 'bg-red-500/15 text-red-600 dark:text-red-400',
  attention: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  pending: 'bg-muted text-muted-foreground',
}

const StepMarker = ({ index, state }: { index: number; state: StepState }) => {
  const icon = { done: <Check size={14} />, running: <Loader2 size={14} className="animate-spin" />, failed: <AlertTriangle size={13} />, attention: <Eye size={13} />, pending: null }[state]
  return (
    <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums', STATE_STYLE[state])} aria-hidden>
      {icon ?? index + 1}
    </span>
  )
}

const StepRowTitle = ({ card, index, state, open }: { card: MacroStepCardDef; index: number; state: StepState; open: boolean }) => (
  <div className="flex min-w-0 items-center gap-3">
    <StepMarker index={index} state={state} />
    <div className="min-w-0">
      <p className={cn('truncate text-sm font-medium', open ? 'text-foreground' : 'text-foreground/90')}>{card.title}</p>
      <p className="truncate text-xs text-muted-foreground">{card.metricPrimary} · {card.metricSecondary}</p>
    </div>
  </div>
)

const AboutAgent = ({ card }: { card: MacroStepCardDef }) => (
  <Disclosure
    title={<span className="text-xs text-muted-foreground">About this step</span>}
    triggerClassName="py-1"
    contentClassName="grid gap-2 pb-2 pt-1 text-xs text-muted-foreground sm:grid-cols-2"
  >
    <p><span className="font-medium text-foreground">Uses: </span>{card.inputsSummary}</p>
    <p><span className="font-medium text-foreground">Produces: </span>{card.outputsSummary}</p>
    <p className="sm:col-span-2">{card.summaryText}</p>
  </Disclosure>
)

/** Vertical stepper: one row per macro step; only expanded steps render their full workspace. */
export const StudioStepAccordion = ({ items, isExpanded, onToggle, renderStep }: StudioStepAccordionProps) => (
  <ol className="divide-y divide-border/60 overflow-hidden rounded-2xl bg-card/70 shadow-sm ring-1 ring-border/60">
    {items.map(({ card, state }, index) => {
      const open = isExpanded(card.id)
      return (
        <li key={card.id} id={`step-${card.id}`} className={cn('transition-colors', open && 'bg-background/40')}>
          <Disclosure
            open={open}
            onOpenChange={(o) => onToggle(card.id, o)}
            title={<StepRowTitle card={card} index={index} state={state} open={open} />}
            summary={<span className={cn('hidden rounded-full px-2 py-0.5 text-[11px] sm:inline', STATE_STYLE[state])}>{STATE_LABEL[state]}</span>}
            triggerClassName="px-4 py-3.5 hover:bg-muted/40 sm:px-5"
            contentClassName="space-y-4 px-4 pb-6 sm:px-5"
          >
            <AboutAgent card={card} />
            {renderStep(card.id)}
          </Disclosure>
        </li>
      )
    })}
  </ol>
)
