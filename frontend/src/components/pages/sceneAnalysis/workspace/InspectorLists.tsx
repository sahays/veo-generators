import { useMemo } from 'react'
import { Badge } from '@/components/ui/badge'
import { EntityRow, GlyphIcon, PanelSearch } from '@/components/shared/timeline'
import { useWorkspace } from '@/hooks/timeline/timelineContext'
import { MAX_PINNED_ENTITIES } from '@/store/timeline/workspaceStore'
import type { TimelineAdOpportunity, TimelineBeat, TimelineDoc, TimelineEvent, TimelineKeyMoment } from '@/types/insights'
import { categoryLabel, glyphFor } from '@/types/timeline/glyphs'
import { matchesQuery } from '@/types/timeline/textSearch'
import { TimedRow, TimedSection } from './TimedList'

function MomentRow({ moment }: { moment: TimelineKeyMoment }): JSX.Element {
  const glyph = glyphFor(moment.type)
  const range = { start_sec: moment.start_sec, end_sec: moment.start_sec }
  return (
    <TimedRow
      selection={{ kind: 'moment', id: moment.id, label: moment.label, range }}
      title={moment.label}
      subtitle={categoryLabel(moment.type)}
      leading={<GlyphIcon shape={glyph.shape} color={glyph.color} />}
    />
  )
}

function BeatRow({ beat }: { beat: TimelineBeat }): JSX.Element {
  const glyph = glyphFor(beat.beat)
  return (
    <TimedRow
      selection={{ kind: 'beat', id: beat.id, label: beat.label || beat.beat, range: beat }}
      title={categoryLabel(beat.beat)}
      subtitle={beat.label}
      leading={<span aria-hidden className="block h-3 w-3 rounded-[3px]" style={{ background: glyph.color, opacity: 0.6 }} />}
    />
  )
}

/** Key moments (with the same glyphs as the timeline lane, so this doubles as its legend) and narrative beats. */
export function MomentsTab({ doc }: { doc: TimelineDoc }): JSX.Element {
  const query = useWorkspace((state) => state.search)
  const moments = useMemo(() => doc.key_moments.filter((m) => matchesQuery(query, m.label, m.type, categoryLabel(m.type))), [doc, query])
  const beats = useMemo(() => doc.narrative_beats.filter((b) => matchesQuery(query, b.label, b.beat, categoryLabel(b.beat))), [doc, query])
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PanelSearch placeholder="Search moments and beats" />
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
        <TimedSection title="Key moments" count={moments.length}>
          {moments.map((moment) => <MomentRow key={moment.id} moment={moment} />)}
        </TimedSection>
        <TimedSection title="Narrative beats" count={beats.length}>
          {beats.map((beat) => <BeatRow key={beat.id} beat={beat} />)}
        </TimedSection>
      </div>
    </div>
  )
}

function IntensityMeter({ value, label = 'Intensity' }: { value: number | undefined; label?: string }): JSX.Element | null {
  if (value === undefined) return null
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <span className="mt-1 block" title={`${label} ${percent}%`}>
      <span className="sr-only">{label} {percent}%</span>
      <span aria-hidden className="block h-1 w-12 overflow-hidden rounded-full bg-muted">
        <span className="block h-full rounded-full bg-accent/80" style={{ width: `${percent}%` }} />
      </span>
    </span>
  )
}

function EventRow({ event }: { event: TimelineEvent }): JSX.Element {
  const tag = categoryLabel(event.tag)
  return (
    <TimedRow
      selection={{ kind: 'event', id: event.id, label: event.description || tag, range: event }}
      title={event.description || tag}
      leading={<Badge variant="accent">{tag}</Badge>}
      trailing={<IntensityMeter value={event.intensity} />}
    />
  )
}

/** Tagged events (action, comedy, product showcase, ...) with their intensity. */
export function EventsTab({ doc }: { doc: TimelineDoc }): JSX.Element {
  const query = useWorkspace((state) => state.search)
  const events = useMemo(() => doc.events.filter((e) => matchesQuery(query, e.description, e.tag, categoryLabel(e.tag))), [doc, query])
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <PanelSearch placeholder="Search events" />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
        <TimedSection title="Events" count={events.length}>
          {events.map((event) => <EventRow key={event.id} event={event} />)}
        </TimedSection>
      </div>
    </div>
  )
}

function AdOpportunityRow({ opportunity }: { opportunity: TimelineAdOpportunity }): JSX.Element {
  const placement = categoryLabel(opportunity.placement_type)
  const title = opportunity.surface_or_trigger
    ? `${opportunity.suggested_category} · ${opportunity.surface_or_trigger}`
    : opportunity.suggested_category
  return (
    <TimedRow
      selection={{ kind: 'ad_opportunity', id: opportunity.id, label: opportunity.suggested_category, range: opportunity }}
      title={title}
      subtitle={opportunity.rationale}
      leading={<Badge variant="accent">{placement}</Badge>}
      trailing={<IntensityMeter value={opportunity.suitability} label="Suitability" />}
    />
  )
}

/** Object identification (`kind === 'object'`) and timestamped ad insertion / placement opportunities. */
export function ObjectsAdsTab({ doc }: { doc: TimelineDoc }): JSX.Element {
  const query = useWorkspace((state) => state.search)
  const pinnedCount = useWorkspace((state) => state.pinnedEntityIds.length)
  const opportunities = useMemo(
    () =>
      (doc.ad_opportunities ?? []).filter((a) =>
        matchesQuery(query, a.suggested_category, a.surface_or_trigger, a.rationale, a.placement_type, categoryLabel(a.placement_type)),
      ),
    [doc, query],
  )
  const objects = useMemo(
    () => doc.entities.filter((e) => e.kind === 'object' && matchesQuery(query, e.name, e.description)),
    [doc, query],
  )
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-2">
        <PanelSearch placeholder="Search objects and ad opportunities" className="flex-1" />
        <span aria-live="polite" className="text-[10px] tabular-nums text-muted-foreground">{pinnedCount}/{MAX_PINNED_ENTITIES} pinned</span>
      </div>
      <div data-testid="objects-ads-list" className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
        <TimedSection title="Ad insertion opportunities" count={opportunities.length}>
          {opportunities.map((opportunity) => <AdOpportunityRow key={opportunity.id} opportunity={opportunity} />)}
        </TimedSection>
        <TimedSection title="Identified objects" count={objects.length}>
          {objects.map((entity) => <EntityRow key={entity.id} entity={entity} duration={doc.duration_sec} query={query} />)}
        </TimedSection>
      </div>
    </div>
  )
}
