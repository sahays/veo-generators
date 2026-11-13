import { useCallback } from 'react'
import { GlyphIcon } from '@/components/shared/timeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useTimelineKit, useWorkspace } from '@/hooks/timeline/timelineContext'
import { useClockValue } from '@/hooks/timeline/useMediaClock'
import { cn } from '@/lib/utils'
import { formatValue } from '@/types/engagement/reportFormat'
import { EXTREMUM_STYLE, extremumTitle, nearestExtremum, type ReportModel } from '@/types/engagement/reportModel'
import type { ReportExtremum } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge, EmptyProse } from '../ReportBits'
import { useFocusExtremum } from '../workspace/useFocusExtremum'

const sameId = (id: string | null): string | null => id

/** Id of the extremum closest to the playhead. Changes only when the playhead moves closer to another one. */
function useNearestExtremumId(report: ReportModel): string | null {
  const { clock } = useTimelineKit()
  const nearestId = useCallback((timeSec: number) => nearestExtremum(report, timeSec)?.id ?? null, [report])
  return useClockValue(clock, nearestId, sameId)
}

function ExtremumProse({ extremum }: { extremum: ReportExtremum }): JSX.Element {
  if (!extremum.explanation) {
    return <span className="block text-[11px] italic leading-snug text-muted-foreground">No explanation was written for this moment.</span>
  }
  return <span className="block text-xs leading-snug text-muted-foreground">{extremum.explanation}</span>
}

/** What the explanation ties the moment to. Worded as coincidence: the report shows association, not cause. */
function DriverChips({ drivers }: { drivers: readonly string[] }): JSX.Element | null {
  if (drivers.length === 0) return null
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span className="text-[10px] text-muted-foreground">Coincides with</span>
      {drivers.map((driver) => (
        <Badge key={driver} variant="outline">{driver}</Badge>
      ))}
    </span>
  )
}

/** Glyph, kind and time; the card nearest the playhead says so in words as well as with a ring. */
function ExtremumKindLine({ extremum, nearest }: { extremum: ReportExtremum; nearest: boolean }): JSX.Element {
  const style = EXTREMUM_STYLE[extremum.kind]
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <GlyphIcon shape={style.glyph.shape} color={style.glyph.color} />
      <span className="font-semibold text-foreground">{style.label}</span>
      <span className="font-mono">{formatTimecode(extremum.time_sec)}</span>
      {nearest && <Badge variant="accent" className="ml-auto">Nearest to playhead</Badge>}
    </span>
  )
}

/**
 * The figure that defines the moment. A peak or valley is its value against
 * the average; a drop is the size of the fall, from the value it starts at.
 */
function ExtremumFigure({ extremum, unit }: { extremum: ReportExtremum; unit: string }): JSX.Element {
  if (extremum.kind === 'drop') {
    return (
      <>
        <span className="font-mono text-sm font-semibold tabular-nums text-foreground">{formatValue(-extremum.prominence, unit)}</span>
        <span className="text-[11px] text-muted-foreground">fall, from {formatValue(extremum.value, unit)}</span>
      </>
    )
  }
  return (
    <>
      <span className="font-mono text-sm font-semibold tabular-nums text-foreground">{formatValue(extremum.value, unit)}</span>
      <DeltaBadge pct={extremum.delta_pct} />
    </>
  )
}

interface ExtremumCardProps {
  extremum: ReportExtremum
  segmentTitle: string | null
  unit: string
  nearest: boolean
}

/** One peak, valley or drop. The whole card is a button: it seeks there and zooms the timeline to the moment's window. */
function ExtremumCard({ extremum, segmentTitle, unit, nearest }: ExtremumCardProps): JSX.Element {
  const focus = useFocusExtremum()
  const selected = useWorkspace((state) => state.selection?.id === extremum.id)
  return (
    <li>
      <Button
        variant="unstyled"
        aria-pressed={selected}
        aria-current={nearest ? 'true' : undefined}
        data-testid={`extremum-${extremum.id}`}
        data-nearest={nearest}
        onClick={() => focus(extremum)}
        className={cn('flex h-full w-full flex-col gap-2 rounded-lg border p-3 text-left transition-colors hover:bg-muted/50', selected ? 'border-accent/60 bg-accent/10' : 'border-border/70 bg-card', nearest && 'ring-2 ring-accent/50')}
      >
        <ExtremumKindLine extremum={extremum} nearest={nearest} />
        <span className="block text-sm font-semibold leading-snug text-foreground">{extremumTitle(extremum)}</span>
        <ExtremumProse extremum={extremum} />
        <DriverChips drivers={extremum.drivers} />
        <span className="mt-auto flex flex-wrap items-center gap-2 pt-1">
          <ExtremumFigure extremum={extremum} unit={unit} />
          {segmentTitle && <span className="min-w-0 truncate text-[11px] text-muted-foreground">in “{segmentTitle}”</span>}
        </span>
      </Button>
    </li>
  )
}

export interface ExtremaTabProps {
  report: ReportModel
  timeline: TimelineModel
}

/** Peaks, valleys and drops as cards, most prominent first within each kind. */
export function ExtremaTab({ report, timeline }: ExtremaTabProps): JSX.Element {
  const nearestId = useNearestExtremumId(report)
  const extrema = report.report.extrema
  const unit = report.report.signal.unit
  if (extrema.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">The curve has no distinct peaks, valleys or drops.</p>
  }
  const noProse = extrema.every((extremum) => !extremum.title && !extremum.explanation)
  return (
    <div className="space-y-3">
      {noProse && (
        <EmptyProse title="Explanations were not generated.">
          The language-model step did not return usable text for this report. The moments below, their times and their figures are complete.
        </EmptyProse>
      )}
      <ul aria-label="Peaks, valleys and drops" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {extrema.map((extremum) => (
          <ExtremumCard key={extremum.id} extremum={extremum} segmentTitle={timeline.itemsById.get(extremum.segment_id ?? '')?.label ?? null} unit={unit} nearest={extremum.id === nearestId} />
        ))}
      </ul>
    </div>
  )
}
