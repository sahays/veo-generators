import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'
import { splitHighlight } from '@/types/timeline/textSearch'

export interface PanelSearchProps {
  placeholder: string
  className?: string
}

/**
 * Search box bound to the workspace's shared query, so the same search
 * carries across the transcript, the entity browser and any other panel.
 * It is a block-level box; in a row of controls pass `className="flex-1"`.
 */
export function PanelSearch({ placeholder, className }: PanelSearchProps): JSX.Element {
  const { store } = useTimelineKit()
  const search = useWorkspace((state) => state.search)
  return (
    <div className={cn('relative min-w-0', className)}>
      <Search aria-hidden size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <Input
        type="search"
        value={search}
        placeholder={placeholder}
        aria-label={placeholder}
        data-testid="panel-search"
        className="h-8 py-1 pl-8 text-xs"
        onChange={(event) => store.getState().setSearch(event.target.value)}
      />
    </div>
  )
}

/** Text with every occurrence of the query marked. */
export function Highlighted({ text, query }: { text: string; query: string }): JSX.Element {
  return (
    <>
      {splitHighlight(text, query).map((part, i) =>
        part.match ? (
          <mark key={i} className="rounded-sm bg-accent/30 px-0.5 text-foreground">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  )
}
