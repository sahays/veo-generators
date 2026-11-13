import { Button } from '@/components/ui/button'
import { Highlighted } from '@/components/shared/timeline'
import { useSelectItem, useWorkspace } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'
import type { TimelineSelection } from '@/store/timeline/workspaceStore'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'

export interface TimedRowProps {
  /** What clicking the row selects (and seeks to). */
  selection: TimelineSelection
  title: string
  subtitle?: string
  /** Icon or badge before the text. */
  leading?: React.ReactNode
  /** Extra content on the right, e.g. an intensity. */
  trailing?: React.ReactNode
}

/** One clickable, timestamped line in an inspector list. Highlights when it is the selected item. */
export function TimedRow({ selection, title, subtitle, leading, trailing }: TimedRowProps): JSX.Element {
  const select = useSelectItem()
  const query = useWorkspace((state) => state.search)
  const selected = useWorkspace((state) => state.selection?.id === selection.id)
  const { start_sec, end_sec } = selection.range
  return (
    <li>
      <Button
        variant="unstyled"
        aria-pressed={selected}
        className={cn('flex w-full items-start gap-2.5 rounded-md border px-2.5 py-2 text-left transition-colors hover:bg-muted/60', selected ? 'border-accent/50 bg-accent/10' : 'border-border/70 bg-card')}
        onClick={() => select(selection)}
      >
        {leading && <span className="mt-0.5 shrink-0">{leading}</span>}
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold leading-snug text-foreground"><Highlighted text={title} query={query} /></span>
          {subtitle && <span className="block text-[11px] leading-snug text-muted-foreground"><Highlighted text={subtitle} query={query} /></span>}
        </span>
        <span className="shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatTimecode(start_sec)}
          {end_sec > start_sec && <span className="block">{formatSpan(end_sec - start_sec)}</span>}
          {trailing}
        </span>
      </Button>
    </li>
  )
}

export interface TimedSectionProps {
  title: string
  count: number
  children: React.ReactNode
}

/** Titled list of `TimedRow`s with an empty state for a search that matches nothing. */
export function TimedSection({ title, count, children }: TimedSectionProps): JSX.Element {
  return (
    <section aria-label={title} className="space-y-1.5">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        {title} <span className="font-normal">({count})</span>
      </h4>
      {count === 0 ? <p className="py-3 text-xs text-muted-foreground">Nothing matches.</p> : <ul className="space-y-1.5">{children}</ul>}
    </section>
  )
}
