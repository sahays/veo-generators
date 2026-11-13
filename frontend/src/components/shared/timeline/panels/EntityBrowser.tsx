import { useMemo, useState } from 'react'
import { MapPin, Package, User, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { useSelectItem, useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import { cn } from '@/lib/utils'
import type { EntityKind, TimeRange, TimelineEntity } from '@/types/insights'
import { MAX_PINNED_ENTITIES } from '@/store/timeline/workspaceStore'
import { matchesQuery } from '@/types/timeline/textSearch'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'
import { Highlighted, PanelSearch } from './PanelSearch'

const COLLAPSED_APPEARANCES = 6

const KIND_GROUPS: { kind: EntityKind; label: string; icon: LucideIcon }[] = [
  { kind: 'character', label: 'Characters', icon: User },
  { kind: 'object', label: 'Objects', icon: Package },
  { kind: 'location', label: 'Locations', icon: MapPin },
]

/** Checkbox that pins the entity as a lane on the timeline. */
function PinToggle({ entity }: { entity: TimelineEntity }): JSX.Element {
  const { store } = useTimelineKit()
  const pinned = useWorkspace((state) => state.pinnedEntityIds.includes(entity.id))
  const full = useWorkspace((state) => state.pinnedEntityIds.length >= MAX_PINNED_ENTITIES)
  const label = pinned ? `Unpin ${entity.name} from the timeline` : `Pin ${entity.name} to the timeline`
  return (
    <Checkbox
      checked={pinned}
      disabled={full && !pinned}
      aria-label={label}
      title={full && !pinned ? `Up to ${MAX_PINNED_ENTITIES} entities can be pinned` : label}
      data-testid={`pin-${entity.id}`}
      className="h-4 w-4 rounded"
      onCheckedChange={() => store.getState().togglePin(entity.id)}
    />
  )
}

function AppearanceChips({ entity }: { entity: TimelineEntity }): JSX.Element {
  const select = useSelectItem()
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? entity.appearances : entity.appearances.slice(0, COLLAPSED_APPEARANCES)
  const hiddenCount = entity.appearances.length - shown.length
  const seekTo = (range: TimeRange): void => select({ kind: 'entity', id: entity.id, label: entity.name, range })
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((range) => (
        <Button key={range.start_sec} variant="outline" size="none" className="rounded px-1.5 py-0.5 font-mono text-[10px] tabular-nums" aria-label={`${entity.name} at ${formatTimecode(range.start_sec)}, for ${formatSpan(range.end_sec - range.start_sec)}`} onClick={() => seekTo(range)}>
          {formatTimecode(range.start_sec)}–{formatTimecode(range.end_sec)}
        </Button>
      ))}
      {hiddenCount > 0 && (
        <Button variant="link" className="text-[10px]" onClick={() => setExpanded(true)}>
          +{hiddenCount} more
        </Button>
      )}
    </div>
  )
}

export interface EntityRowProps {
  entity: TimelineEntity
  duration: number
  query: string
}

export function EntityRow({ entity, duration, query }: EntityRowProps): JSX.Element {
  const share = duration > 0 ? Math.min(entity.screen_time_sec / duration, 1) : 0
  const first = entity.appearances[0]
  return (
    <li className="space-y-1.5 rounded-md border border-border/70 bg-card px-2.5 py-2">
      <div className="flex items-center gap-2">
        <PinToggle entity={entity} />
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">
          <Highlighted text={entity.name} query={query} />
        </span>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground" title="Screen time">
          {formatSpan(entity.screen_time_sec)} · {Math.round(share * 100)}%
        </span>
      </div>
      <div aria-hidden className="h-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-accent/70" style={{ width: `${share * 100}%` }} />
      </div>
      {entity.description && <p className="text-[11px] leading-snug text-muted-foreground"><Highlighted text={entity.description} query={query} /></p>}
      <p className="text-[10px] text-muted-foreground">
        First appears at <span className="font-mono text-foreground">{first ? formatTimecode(first.start_sec) : '–'}</span> · {entity.appearances.length} appearance{entity.appearances.length === 1 ? '' : 's'}
      </p>
      <AppearanceChips entity={entity} />
    </li>
  )
}

interface EntityGroupProps {
  label: string
  icon: LucideIcon
  entities: TimelineEntity[]
  duration: number
  query: string
}

function EntityGroup({ label, icon: Icon, entities, duration, query }: EntityGroupProps): JSX.Element | null {
  if (entities.length === 0) return null
  return (
    <section aria-label={label} className="space-y-1.5">
      <h4 className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        <Icon size={11} /> {label} <span className="font-normal">({entities.length})</span>
      </h4>
      <ul className="space-y-1.5">
        {entities.map((entity) => (
          <EntityRow key={entity.id} entity={entity} duration={duration} query={query} />
        ))}
      </ul>
    </section>
  )
}

export interface EntityBrowserProps {
  /** Entities in document order (descending screen time). */
  entities: readonly TimelineEntity[]
  className?: string
}

/**
 * Entities grouped by kind, with search, screen time and first appearance.
 * Tick several to pin them as lanes on the timeline and compare them; click
 * an appearance to select it and seek there.
 */
export function EntityBrowser({ entities, className }: EntityBrowserProps): JSX.Element {
  const { duration } = useTimelineKit()
  const query = useWorkspace((state) => state.search)
  const pinnedCount = useWorkspace((state) => state.pinnedEntityIds.length)
  const matching = useMemo(() => entities.filter((e) => matchesQuery(query, e.name, e.description)), [entities, query])
  return (
    <div className={cn('flex min-h-0 flex-col gap-2', className)}>
      <div className="flex items-center gap-2">
        <PanelSearch placeholder="Search entities" className="flex-1" />
        <span aria-live="polite" className="text-[10px] tabular-nums text-muted-foreground">{pinnedCount}/{MAX_PINNED_ENTITIES} pinned</span>
      </div>
      <div data-testid="entity-list" className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
        {KIND_GROUPS.map((group) => (
          <EntityGroup key={group.kind} label={group.label} icon={group.icon} entities={matching.filter((e) => e.kind === group.kind)} duration={duration} query={query} />
        ))}
        {matching.length === 0 && <p className="py-8 text-center text-xs text-muted-foreground">No entities match.</p>}
      </div>
    </div>
  )
}
