import { useMemo } from 'react'
import { Badge } from '@/components/ui/badge'
import { GlyphIcon, PanelSearch } from '@/components/shared/timeline'
import { useWorkspace } from '@/hooks/timeline/timelineContext'
import type { TimelineBeat, TimelineDoc, TimelineEvent, TimelineKeyMoment } from '@/types/insights'
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

function IntensityMeter({ value }: { value: number | undefined }): JSX.Element | null {
  if (value === undefined) return null
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100)
  return (
    <span className="mt-1 block" title={`Intensity ${percent}%`}>
      <span className="sr-only">Intensity {percent}%</span>
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
