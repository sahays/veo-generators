import { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { useSeek } from '@/hooks/timeline/timelineContext'
import { useWindowedList } from '@/hooks/timeline/useWindowedList'
import { curveTable } from '@/types/engagement/reportExport'
import { formatValue, reportBadgeText } from '@/types/engagement/reportFormat'
import type { ReportModel } from '@/types/engagement/reportModel'
import type { EngagementRecord } from '@/types/insights'
import type { CsvValue } from '@/types/timeline/exporters'
import { formatSpan, formatTimecode } from '@/types/timeline/timeFormat'

const ROW_PX = 28

interface Fact {
  label: string
  value: string
}

/** Where the signal came from and how it was read. For BARC this includes the column mapping and the offset. */
function signalFacts(report: ReportModel, record: EngagementRecord): Fact[] {
  const { signal, duration_sec } = report.report
  const badge = reportBadgeText(signal)
  const facts: Fact[] = [
    { label: 'Source', value: `${badge.kind} · ${badge.detail}` },
    { label: 'Primary metric', value: signal.primary_metric },
    { label: 'Unit', value: signal.unit || 'not stated' },
    { label: 'Samples', value: `${signal.point_count.toLocaleString('en-US')}, one every ${formatSpan(signal.interval_sec)}` },
    { label: 'Video length', value: formatSpan(duration_sec) },
  ]
  // On a completed job `stage_detail` holds the worker's notes, e.g. rows the offset pushed before the start.
  if (record.stage_detail) facts.push({ label: 'Job notes', value: record.stage_detail })
  if (signal.kind !== 'barc') return facts
  return [
    ...facts,
    { label: 'Time column', value: record.signal.time_column || 'detected automatically' },
    { label: 'Metric column', value: record.signal.metric || 'detected automatically' },
    { label: 'Offset', value: `${signal.offset_sec} s added to every timestamp` },
  ]
}

function statFacts(report: ReportModel): Fact[] {
  const { stats, signal } = report.report
  const entries: [string, number][] = [['Average', stats.avg], ['Median', stats.median], ['75th percentile', stats.p75], ['Lowest', stats.min], ['Highest', stats.max], ['Std. deviation', stats.std]]
  return entries.map(([label, value]) => ({ label, value: formatValue(value, signal.unit) }))
}

function FactList({ title, facts }: { title: string; facts: readonly Fact[] }): JSX.Element {
  return (
    <section aria-label={title} className="space-y-1.5">
      <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{title}</h4>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
        {facts.map((fact) => (
          <div key={fact.label} className="contents">
            <dt className="text-muted-foreground">{fact.label}</dt>
            <dd className="break-words font-medium text-foreground">{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function PointRow({ row, index }: { row: readonly CsvValue[]; index: number }): JSX.Element {
  const seek = useSeek()
  const time = Number(row[0])
  return (
    <tr style={{ height: ROW_PX }} className="border-t border-border/50">
      <td className="px-2.5 text-muted-foreground">{index + 1}</td>
      <td className="px-2.5">
        <Button variant="link" className="font-mono text-[11px] text-accent-dark" aria-label={`Go to ${formatTimecode(time, { tenths: true })}`} onClick={() => seek(time)}>
          {formatTimecode(time, { tenths: true })}
        </Button>
      </td>
      {row.slice(1).map((value, column) => (
        <td key={column} className="px-2.5 text-right">{typeof value === 'number' ? formatValue(value) : '—'}</td>
      ))}
    </tr>
  )
}

/**
 * Every sample of the curve. Only the rows near the scroll position are in
 * the DOM; two spacer rows stand in for the rest, so a long signal stays cheap.
 */
function PointsTable({ report }: { report: ReportModel }): JSX.Element {
  const table = useMemo(() => curveTable(report.report), [report])
  const heights = useMemo(() => new Array<number>(table.rows.length).fill(ROW_PX), [table])
  const { containerRef, window: visible } = useWindowedList(heights)
  const spacer = (height: number): JSX.Element | null => (height > 0 ? <tr aria-hidden style={{ height }}><td colSpan={table.columns.length + 1} /></tr> : null)
  return (
    <div ref={containerRef} data-testid="points-table" tabIndex={0} role="region" aria-label={`Signal points, ${table.rows.length} rows`} className="tl-focusable h-80 overflow-y-auto rounded-lg border border-border">
      <table className="w-full font-mono text-[11px] tabular-nums text-foreground">
        <thead className="sticky top-0 z-10 bg-muted text-muted-foreground">
          <tr style={{ height: ROW_PX }}>
            <th scope="col" className="px-2.5 text-left font-medium">#</th>
            <th scope="col" className="px-2.5 text-left font-medium">Time</th>
            {table.columns.slice(1).map((column) => <th key={column} scope="col" className="px-2.5 text-right font-medium">{column}</th>)}
          </tr>
        </thead>
        <tbody>
          {spacer(visible.padTop)}
          {table.rows.slice(visible.start, visible.end).map((row, i) => <PointRow key={visible.start + i} row={row} index={visible.start + i} />)}
          {spacer(visible.padBottom)}
        </tbody>
      </table>
    </div>
  )
}

export interface DataTabProps {
  report: ReportModel
  record: EngagementRecord
}

/** The parsed signal: where it came from, how it was mapped and aligned, its statistics and every point. */
export function DataTab({ report, record }: DataTabProps): JSX.Element {
  const signal = useMemo(() => signalFacts(report, record), [report, record])
  const stats = useMemo(() => statFacts(report), [report])
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <div className="space-y-4">
        <FactList title="Signal" facts={signal} />
        <FactList title={`Statistics of ${report.primary.label}`} facts={stats} />
      </div>
      <PointsTable report={report} />
    </div>
  )
}
