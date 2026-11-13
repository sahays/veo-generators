import { useState } from 'react'
import { ArrowLeft, Clock, Download, Loader2, RotateCcw, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EditableNameField } from '@/components/shared/EditableNameField'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { UNIFIED_STATUS_LABELS, UNIFIED_STATUS_STYLES } from '@/hooks/jobStatus'
import { cn } from '@/lib/utils'
import { formatTimecode } from '@/types/timeline/timeFormat'

/** "Back to …" link above a record page. */
export function BackLink({ to, label }: { to: string; label: string }): JSX.Element {
  return (
    <Button asChild variant="link" className="text-xs">
      <Link to={to}>
        <ArrowLeft size={13} aria-hidden /> {label}
      </Link>
    </Button>
  )
}

/** Job status as a pill, in the app's shared status colours. */
export function RecordStatusPill({ status }: { status: string }): JSX.Element {
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', UNIFIED_STATUS_STYLES[status] ?? UNIFIED_STATUS_STYLES.pending)}>
      {UNIFIED_STATUS_LABELS[status] ?? status}
    </span>
  )
}

/** Video length as a small pill, for record cards. */
export function DurationPill({ seconds }: { seconds: number }): JSX.Element {
  return (
    <span title="Video length" className="flex shrink-0 items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">
      <Clock size={10} aria-hidden="true" />
      {formatTimecode(seconds)}
    </span>
  )
}

export interface RecordHeaderProps {
  backTo: string
  backLabel: string
  /** Name shown for the record. */
  name: string
  /** Shown when the name is empty. */
  defaultName?: string
  /** Saves a new name. The header shows it once the promise resolves. */
  onRename: (name: string) => Promise<unknown>
  /** Status, source and other badges under the name. */
  badges?: React.ReactNode
  /** Buttons on the right (Export, ...). */
  actions?: React.ReactNode
}

/** Header of a record page: back link, editable name, badges and the page actions. */
export function RecordHeader({ backTo, backLabel, name, defaultName = 'Untitled video', onRename, badges, actions }: RecordHeaderProps): JSX.Element {
  const [savedName, setSavedName] = useState<string | null>(null)
  const saveName = async (next: string): Promise<void> => {
    await onRename(next)
    setSavedName(next)
  }
  return (
    <header className="space-y-2">
      <BackLink to={backTo} label={backLabel} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <EditableNameField value={savedName ?? name} onSave={saveName} defaultText={defaultName} />
          <div className="flex flex-wrap items-center gap-1.5">{badges}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      </div>
    </header>
  )
}

/** Centred spinner with a label, for a record or document that is loading. */
export function LoadingNotice({ label, className }: { label: string; className?: string }): JSX.Element {
  return (
    <div role="status" className={cn('flex flex-col items-center justify-center gap-3 py-24 text-sm text-muted-foreground', className)}>
      <Loader2 size={24} className="animate-spin text-accent motion-reduce:animate-none" /> {label}
    </div>
  )
}

/** A load error with a "Try again" button. */
export function LoadFailure({ error, onRetry }: { error: string; onRetry: () => void }): JSX.Element {
  return (
    <div role="alert" className="space-y-3">
      <ErrorDisplay error={error} size="md" />
      <Button variant="outline" icon={RotateCcw} onClick={onRetry}>Try again</Button>
    </div>
  )
}

export interface RecordUnavailableProps {
  /** Null while the record is still loading. */
  error: string | null
  loadingLabel: string
  backTo: string
  backLabel: string
}

/** What a record page shows before it has a record: a spinner, or the error with a way back. */
export function RecordUnavailable({ error, loadingLabel, backTo, backLabel }: RecordUnavailableProps): JSX.Element {
  if (!error) return <LoadingNotice label={loadingLabel} className="py-32" />
  return (
    <div role="alert" className="space-y-3">
      <BackLink to={backTo} label={backLabel} />
      <ErrorDisplay error={error} size="md" />
    </div>
  )
}

export interface DownloadItem {
  key: string
  label: string
  icon: LucideIcon
  /** Generates the file and offers it for download. */
  save: () => void
}

export interface DownloadGroup {
  /** Heading above the group's items. */
  label?: string
  items: DownloadItem[]
}

/** "Export" button with a menu of downloads generated in the browser. Groups are separated by rules. */
export function DownloadMenu({ groups }: { groups: readonly DownloadGroup[] }): JSX.Element {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" icon={Download} data-testid="export-menu">
          Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {groups.map((group, i) => (
          <div key={group.label ?? i} role="group" aria-label={group.label}>
            {i > 0 && <DropdownMenuSeparator />}
            {group.label && <DropdownMenuLabel>{group.label}</DropdownMenuLabel>}
            {group.items.map((item) => (
              <DropdownMenuItem key={item.key} icon={item.icon} onSelect={item.save}>
                {item.label}
              </DropdownMenuItem>
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
