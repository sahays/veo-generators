import { useId } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/select'
import { parseOffset, previewIssues, type BarcSelection } from '@/types/engagement/createForm'
import type { SignalPreview } from '@/types/insights'
import { formatSpan } from '@/types/timeline/timeFormat'

const LABEL_CLASS = 'block text-xs font-medium text-foreground'

/** Every column of the file; the ones mapped to the time axis or to a metric are marked. */
function ColumnChips({ preview }: { preview: SignalPreview }): JSX.Element {
  const metrics = new Set(preview.metrics)
  const role = (column: string): string => (column === preview.time_column ? 'time' : metrics.has(column) ? 'metric' : '')
  return (
    <div className="space-y-1">
      <h4 className={LABEL_CLASS}>Detected columns</h4>
      <ul aria-label="Detected columns" className="flex flex-wrap gap-1">
        {preview.columns.map((column) => (
          <li key={column}>
            <Badge variant={role(column) ? 'accent' : 'default'}>
              {column}
              {role(column) && <span className="font-normal opacity-80"> · {role(column)}</span>}
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** What is missing (blocks Start) and the server's notes about the file. */
function PreviewNotes({ preview }: { preview: SignalPreview }): JSX.Element | null {
  const issues = previewIssues(preview)
  if (issues.length === 0 && preview.warnings.length === 0) return null
  return (
    <div className="space-y-2">
      {issues.length > 0 && (
        <div role="alert" data-testid="barc-issues" className="space-y-1 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          <p className="font-semibold">This file cannot be used as an engagement signal yet.</p>
          <ul className="list-disc space-y-0.5 pl-4">{issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          <p>Upload a file with these columns to continue.</p>
        </div>
      )}
      {preview.warnings.length > 0 && (
        <div role="status" data-testid="barc-warnings" className="flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0" />
          <ul className="space-y-0.5">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </div>
      )}
    </div>
  )
}

function SampleTable({ preview }: { preview: SignalPreview }): JSX.Element {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table data-testid="barc-sample" className="w-full text-left text-[11px]">
        <caption className="sr-only">First {preview.sample_rows.length} rows of {preview.filename}</caption>
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>{preview.columns.map((column) => <th key={column} scope="col" className="whitespace-nowrap px-2.5 py-1.5 font-medium">{column}</th>)}</tr>
        </thead>
        <tbody className="font-mono text-foreground">
          {preview.sample_rows.map((row, i) => (
            <tr key={i} className="border-t border-border/60">
              {preview.columns.map((column) => <td key={column} className="whitespace-nowrap px-2.5 py-1">{row[column] ?? ''}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface MappingFieldsProps {
  barc: BarcSelection
  preview: SignalPreview
  onChange: (barc: BarcSelection) => void
}

/** Time column, primary metric and alignment offset. Prefilled with what the server detected. */
function MappingFields({ barc, preview, onChange }: MappingFieldsProps): JSX.Element {
  const id = useId()
  const offsetInvalid = parseOffset(barc.offsetText) === null
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="space-y-1">
        <label htmlFor={`${id}-time`} className={LABEL_CLASS}>Time column</label>
        <NativeSelect id={`${id}-time`} data-testid="barc-time-column" className="w-full" value={barc.timeColumn} onChange={(e) => onChange({ ...barc, timeColumn: e.target.value })}>
          {preview.columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </NativeSelect>
      </div>
      <div className="space-y-1">
        <label htmlFor={`${id}-metric`} className={LABEL_CLASS}>Primary metric</label>
        <NativeSelect id={`${id}-metric`} data-testid="barc-metric" className="w-full" value={barc.metric} onChange={(e) => onChange({ ...barc, metric: e.target.value })}>
          {preview.metrics.map((metric) => <option key={metric} value={metric}>{metric}</option>)}
        </NativeSelect>
      </div>
      <div className="space-y-1">
        <label htmlFor={`${id}-offset`} className={LABEL_CLASS}>Offset (seconds)</label>
        <Input id={`${id}-offset`} type="number" step="any" inputMode="decimal" data-testid="barc-offset" aria-describedby={`${id}-offset-help`} aria-invalid={offsetInvalid} value={barc.offsetText} onChange={(e) => onChange({ ...barc, offsetText: e.target.value })} />
        <p id={`${id}-offset-help`} className="text-[11px] leading-snug text-muted-foreground">
          {offsetInvalid ? 'Enter a number of seconds between -86400 and 86400.' : 'Added to every timestamp so the file lines up with the start of the video. Negative when the file starts before the video.'}
        </p>
      </div>
    </div>
  )
}

export interface BarcPreviewProps {
  barc: BarcSelection
  onChange: (barc: BarcSelection) => void
}

/** The server's reading of the uploaded CSV: columns, sample rows, the column mapping and any problems. */
export function BarcPreview({ barc, onChange }: BarcPreviewProps): JSX.Element | null {
  const preview = barc.preview
  if (!preview) return null
  const usable = previewIssues(preview).length === 0
  return (
    <div data-testid="barc-preview" className="space-y-3">
      <p className="text-xs text-foreground">
        <span className="font-semibold">{preview.filename}</span>
        <span className="text-muted-foreground"> · {preview.row_count.toLocaleString('en-US')} rows</span>
        {usable && <span className="text-muted-foreground" data-testid="barc-detected"> · covers {formatSpan(preview.duration_sec)}, one sample every {formatSpan(preview.interval_sec)}</span>}
      </p>
      <ColumnChips preview={preview} />
      <PreviewNotes preview={preview} />
      {usable && <MappingFields barc={barc} preview={preview} onChange={onChange} />}
      <SampleTable preview={preview} />
    </div>
  )
}
