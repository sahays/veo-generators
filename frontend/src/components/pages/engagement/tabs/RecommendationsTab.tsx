import { MapPin, SignalHigh, SignalLow, SignalMedium, ThumbsDown, ThumbsUp, type LucideIcon } from 'lucide-react'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useSeek } from '@/hooks/timeline/timelineContext'
import { driverLabel, formatValue } from '@/types/engagement/reportFormat'
import type { ReportModel } from '@/types/engagement/reportModel'
import { percentDelta } from '@/types/engagement/stepSeries'
import type { RecommendationEvidence, ReportRecommendation, ReportSegmentFix } from '@/types/insights'
import { categoryLabel } from '@/types/timeline/glyphs'
import type { TimelineModel } from '@/types/timeline/model'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'
import { DeltaBadge, EmptyProse } from '../ReportBits'
import { useEngagementUi, useEngagementUiStore } from '../workspace/engagementUi'
import { useShowRange } from '../workspace/useFocusExtremum'

const LIFT: Record<ReportRecommendation['expected_lift'], { label: string; icon: LucideIcon; variant: BadgeProps['variant'] }> = {
  high: { label: 'High expected lift', icon: SignalHigh, variant: 'success' },
  medium: { label: 'Medium expected lift', icon: SignalMedium, variant: 'accent' },
  low: { label: 'Low expected lift', icon: SignalLow, variant: 'default' },
}

function LiftBadge({ lift }: { lift: ReportRecommendation['expected_lift'] }): JSX.Element {
  const { label, icon: Icon, variant } = LIFT[lift]
  return (
    <Badge variant={variant}>
      <Icon size={11} aria-hidden /> {label}
    </Badge>
  )
}

/** The driver a recommendation rests on, with its figures and the times it appears. Each time chip seeks there. */
function Evidence({ evidence }: { evidence: RecommendationEvidence }): JSX.Element {
  const seek = useSeek()
  const store = useEngagementUiStore()
  const shaded = useEngagementUi((state) => state.selectedDrivers.includes(evidence.key))
  const name = driverLabel(evidence)
  return (
    <div data-testid="recommendation-evidence" className="space-y-1.5 rounded-md border border-border/70 bg-muted/30 px-2.5 py-2">
      <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="font-semibold text-foreground">Evidence (association):</span>
        {name} · {categoryLabel(evidence.kind)}
        <DeltaBadge pct={evidence.delta_pct} />
        <span>while present for {formatSpan(evidence.coverage_sec)}</span>
      </p>
      <div className="flex flex-wrap items-center gap-1">
        {evidence.anchor_times.map((time) => (
          <Button key={time} variant="outline" size="xs" className="font-mono" aria-label={`Go to ${formatTimecode(time)}, where ${name} appears`} onClick={() => seek(time)}>
            {formatTimecode(time)}
          </Button>
        ))}
        <Button variant="ghost" size="xs" aria-pressed={shaded} onClick={() => store.getState().toggleDriver(evidence.key)}>
          {shaded ? 'Shaded on timeline' : 'Shade on timeline'}
        </Button>
      </div>
    </div>
  )
}

function RecommendationCard({ item }: { item: ReportRecommendation }): JSX.Element {
  return (
    <li className="space-y-2 rounded-lg border border-border/70 bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h5 className="min-w-0 flex-1 text-sm font-semibold leading-snug text-foreground">{item.title}</h5>
        <LiftBadge lift={item.expected_lift} />
      </div>
      {item.rationale && <p className="text-xs leading-snug text-muted-foreground">{item.rationale}</p>}
      {item.evidence && <Evidence evidence={item.evidence} />}
    </li>
  )
}

interface RecommendationListProps {
  title: string
  icon: LucideIcon
  items: readonly ReportRecommendation[]
}

function RecommendationList({ title, icon: Icon, items }: RecommendationListProps): JSX.Element {
  return (
    <section aria-label={title} className="space-y-2">
      <h4 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">
        <Icon size={13} aria-hidden /> {title} <span className="font-normal">({items.length})</span>
      </h4>
      {items.length === 0 && <p className="text-xs text-muted-foreground">Nothing was suggested here.</p>}
      <ul className="space-y-2">
        {items.map((item) => <RecommendationCard key={item.title} item={item} />)}
      </ul>
    </section>
  )
}

interface SegmentFixCardProps {
  fix: ReportSegmentFix
  title: string
  report: ReportModel
}

function SegmentFixCard({ fix, title, report }: SegmentFixCardProps): JSX.Element {
  const showRange = useShowRange()
  const parts = [['What happens', fix.what_happened], ['Why it is low', fix.why_low], ['Fix', fix.fix]].filter(([, text]) => text)
  return (
    <li data-testid={`segment-fix-${fix.segment_id}`} className="space-y-2 rounded-lg border border-border/70 bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h5 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{title}</h5>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">{formatValue(fix.avg, report.report.signal.unit)}</span>
        <DeltaBadge pct={percentDelta(fix.avg, report.average)} />
        <Button variant="outline" size="xs" icon={MapPin} onClick={() => showRange(fix)}>
          Go to {formatTimecode(fix.start_sec)}
        </Button>
      </div>
      <dl className="space-y-1 text-xs leading-snug">
        {parts.map(([label, text]) => (
          <div key={label}>
            <dt className="inline font-semibold text-foreground">{label}: </dt>
            <dd className="inline text-muted-foreground">{text}</dd>
          </div>
        ))}
      </dl>
    </li>
  )
}

export interface RecommendationsTabProps {
  report: ReportModel
  timeline: TimelineModel
  /** The record's `stage_detail`: on a completed job it says why prose is missing. */
  jobNote: string
}

/** Headline, what to do more and less of (each with its evidence), and fixes for the weakest segments. */
export function RecommendationsTab({ report, timeline, jobNote }: RecommendationsTabProps): JSX.Element {
  const { headline, do_more, do_less, segment_fixes } = report.report.recommendations
  if (!headline && do_more.length + do_less.length + segment_fixes.length === 0) {
    return (
      <EmptyProse title="No recommendations were written.">
        The language-model step did not return usable text for this report{jobNote ? ` (${jobNote})` : ''}. The curve, the moments and the drivers are complete. Starting a new report runs the step again.
      </EmptyProse>
    )
  }
  return (
    <div className="space-y-4">
      {headline && <p className="text-sm font-medium leading-relaxed text-foreground">{headline}</p>}
      <p className="text-[11px] text-muted-foreground">Suggestions are written by a language model from the report's figures. The evidence under each one is an association with the curve, not proof of cause.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <RecommendationList title="Do more" icon={ThumbsUp} items={do_more} />
        <RecommendationList title="Do less" icon={ThumbsDown} items={do_less} />
      </div>
      {segment_fixes.length > 0 && (
        <section aria-label="Segment fixes" className="space-y-2">
          <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Segment fixes <span className="font-normal">({segment_fixes.length})</span></h4>
          <ul className="grid gap-2 lg:grid-cols-2">
            {segment_fixes.map((fix) => <SegmentFixCard key={fix.segment_id} fix={fix} title={timeline.itemsById.get(fix.segment_id)?.label ?? fix.segment_id} report={report} />)}
          </ul>
        </section>
      )}
    </div>
  )
}
