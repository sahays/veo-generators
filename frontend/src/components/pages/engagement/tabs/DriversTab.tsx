import { useId, useMemo } from 'react'
import { AlertTriangle, Check, X } from 'lucide-react'
import { Bar, BarChart, Cell, ReferenceLine, XAxis, YAxis } from 'recharts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChartContainer, ChartTooltip, ChartTooltipContent, activeIndexOf, type ChartConfig } from '@/components/ui/chart'
import { usePrefersReducedMotion } from '@/hooks/timeline/usePrefersReducedMotion'
import { cn } from '@/lib/utils'
import { MAX_SELECTED_DRIVERS } from '@/store/timeline/engagementUiStore'
import { driverLabel, formatDelta, formatValue } from '@/types/engagement/reportFormat'
import type { InfluenceGroup, ReportModel } from '@/types/engagement/reportModel'
import type { ReportInfluence } from '@/types/insights'
import { formatSpan } from '@/types/timeline/timeFormat'
import { DeltaBadge } from '../ReportBits'
import { driverColor, useEngagementUi, useEngagementUiStore } from '../workspace/engagementUi'

/** Height of one driver row; the chart's bands are the same height, so bars sit on their rows. */
const ROW_PX = 36

const CHART_CONFIG: ChartConfig = {
  delta_pct: { label: 'Against average' },
  above: { label: 'Higher while present', color: 'var(--chart-3)' },
  below: { label: 'Lower while present', color: 'var(--chart-6)' },
}

interface DriverToggleProps {
  driver: ReportInfluence
  /** Position in the selection, or -1 when not selected. */
  position: number
  onToggle: (key: string) => void
}

/** One driver as a toggle: name, how long it is present, its figure, and a marker when the support is low. */
function DriverToggle({ driver, position, onToggle }: DriverToggleProps): JSX.Element {
  const selected = position >= 0
  return (
    <Button
      variant="unstyled"
      aria-pressed={selected}
      data-testid={`driver-${driver.key}`}
      onClick={() => onToggle(driver.key)}
      className={cn('flex h-full w-full items-center gap-2 rounded-md border px-2 text-left text-xs transition-colors hover:bg-muted/60', selected ? 'border-accent/50 bg-accent/10' : 'border-transparent')}
    >
      <span aria-hidden className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] border border-border" style={selected ? { background: driverColor(position), borderColor: driverColor(position) } : undefined}>
        {selected && <Check size={10} className="text-background" />}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium text-foreground">{driverLabel(driver)}</span>
      {driver.low_support && (
        <Badge variant="warning" title="Present too briefly for a dependable figure">
          <AlertTriangle size={10} aria-hidden /> Low support
        </Badge>
      )}
      <span className="hidden shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground sm:inline">{formatSpan(driver.coverage_sec)} · {Math.round(driver.coverage_pct)}%</span>
      <DeltaBadge pct={driver.delta_pct} />
    </Button>
  )
}

function tooltipRow(driver: ReportInfluence | undefined, unit: string): JSX.Element | null {
  if (!driver) return null
  return (
    <div className="space-y-0.5">
      <p className="font-medium text-foreground">{driverLabel(driver)}</p>
      <p className="font-mono text-muted-foreground">{formatValue(driver.avg_during, unit)} while present · {formatDelta(driver.delta_pct)} vs average</p>
      <p className="text-muted-foreground">Present for {formatSpan(driver.coverage_sec)} ({Math.round(driver.coverage_pct)}% of the signal){driver.low_support ? ' · low support' : ''}</p>
    </div>
  )
}

interface DivergingBarsProps {
  group: InfluenceGroup
  /** Largest absolute delta of the whole report, so bars compare across groups. */
  extent: number
  unit: string
  onToggle: (key: string) => void
}

/** Diverging bars of `delta_pct` around zero, one band per driver. Low-support drivers are hatched. */
function DivergingBars({ group, extent, unit, onToggle }: DivergingBarsProps): JSX.Element {
  const reducedMotion = usePrefersReducedMotion()
  const hatchId = `low-support-${useId().replace(/:/g, '')}`
  const pick = (index: number | null): void => {
    const driver = index === null ? undefined : group.items[index]
    if (driver) onToggle(driver.key)
  }
  const fill = (driver: ReportInfluence): string => (driver.low_support ? `url(#${hatchId})` : driver.delta_pct >= 0 ? 'var(--color-above)' : 'var(--color-below)')
  return (
    <ChartContainer config={CHART_CONFIG} className="hidden aspect-auto w-full cursor-pointer md:flex" style={{ height: group.items.length * ROW_PX }} role="img" aria-label={`${group.label}: difference from the average while each is present. The rows next to the chart have the same figures.`}>
      <BarChart data={group.items} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 8 }} barSize={14} onClick={(state) => pick(activeIndexOf(state))}>
        <defs>
          <pattern id={hatchId} patternUnits="userSpaceOnUse" width={6} height={6} patternTransform="rotate(45)">
            <rect width={3} height={6} fill="var(--muted-foreground)" />
          </pattern>
        </defs>
        <XAxis type="number" hide domain={[-extent, extent]} />
        <YAxis type="category" dataKey="key" hide />
        <ChartTooltip content={<ChartTooltipContent hideLabel formatter={(_value, _name, item) => tooltipRow(item.payload as ReportInfluence | undefined, unit)} />} />
        <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeOpacity={0.6} />
        <Bar dataKey="delta_pct" radius={3} isAnimationActive={!reducedMotion}>
          {group.items.map((driver) => (
            <Cell key={driver.key} fill={fill(driver)} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

interface DriverGroupProps extends DivergingBarsProps {
  selected: readonly string[]
}

function DriverGroup({ group, extent, unit, selected, onToggle }: DriverGroupProps): JSX.Element {
  return (
    <section aria-label={group.label} data-testid={`driver-group-${group.kind}`} className="space-y-1">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
        {group.label} <span className="font-normal">({group.items.length})</span>
      </h4>
      <div className="grid md:grid-cols-[minmax(0,5fr)_minmax(0,4fr)] md:gap-3">
        <ul>
          {group.items.map((driver) => (
            <li key={driver.key} style={{ height: ROW_PX }} className="py-0.5">
              <DriverToggle driver={driver} position={selected.indexOf(driver.key)} onToggle={onToggle} />
            </li>
          ))}
        </ul>
        <DivergingBars group={group} extent={extent} unit={unit} onToggle={onToggle} />
      </div>
    </section>
  )
}

const nameOf = (report: ReportModel, key: string): string => {
  const driver = report.influenceByKey.get(key)
  return driver ? driverLabel(driver) : key
}

function SelectedChip({ name, color, onRemove }: { name: string; color: string; onRemove: () => void }): JSX.Element {
  return (
    <Button variant="outline" size="xs" aria-label={`Stop shading ${name}`} onClick={onRemove} className="gap-1.5">
      <span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: color }} />
      {name}
      <X size={11} aria-hidden />
    </Button>
  )
}

/** The drivers currently shaded on the timeline, in their colours, each removable. Same height with or without a selection, so the rows below do not move when one is toggled. */
function SelectionSummary({ report, selected }: { report: ReportModel; selected: readonly string[] }): JSX.Element {
  const store = useEngagementUiStore()
  if (selected.length === 0) {
    return <p className="flex min-h-7 items-center text-xs text-muted-foreground">Select up to {MAX_SELECTED_DRIVERS} drivers to shade the time they are present on the curve and compare them in the Drivers lane.</p>
  }
  return (
    <div data-testid="driver-selection" className="flex min-h-7 flex-wrap items-center gap-1.5 text-xs">
      <span className="text-muted-foreground">Shaded on the timeline:</span>
      {selected.map((key, position) => (
        <SelectedChip key={key} name={nameOf(report, key)} color={driverColor(position)} onRemove={() => store.getState().toggleDriver(key)} />
      ))}
      <Button variant="ghost" size="xs" onClick={() => store.getState().clearDrivers()}>Clear all</Button>
    </div>
  )
}

/**
 * Influence ranking grouped by kind. The figures are associations: how the
 * curve behaved while something was present, not what that thing caused.
 */
export function DriversTab({ report }: { report: ReportModel }): JSX.Element {
  const store = useEngagementUiStore()
  const selected = useEngagementUi((state) => state.selectedDrivers)
  const extent = useMemo(() => Math.max(1, ...report.report.influence.map((driver) => Math.abs(driver.delta_pct))), [report])
  if (report.influenceGroups.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">The scene analysis has no characters, objects, locations, emotions or events that overlap the signal.</p>
  }
  return (
    <div className="space-y-4">
      <p role="note" data-testid="association-note" className="text-xs leading-snug text-muted-foreground">
        <span className="font-semibold text-foreground">Associations, not causes.</span> Each figure compares the curve while something was on screen (or an emotion or event was tagged) with the overall average. Things that appear together share the same stretch of curve, so a figure does not show that the item caused the change.
      </p>
      <SelectionSummary report={report} selected={selected} />
      {report.influenceGroups.map((group) => (
        <DriverGroup key={group.kind} group={group} extent={extent} unit={report.report.signal.unit} selected={selected} onToggle={store.getState().toggleDriver} />
      ))}
    </div>
  )
}
