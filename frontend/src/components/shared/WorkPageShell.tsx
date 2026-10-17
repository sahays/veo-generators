import { useState } from 'react'
import { ArrowLeft, Loader2, RotateCcw, type LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/Common'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { ProgressBar } from '@/components/shared/media/ProgressBar'
import { WorkPageHeader } from '@/components/shared/WorkPageHeader'
import { useAuthStore } from '@/store/useAuthStore'
import type { JobStatusConfig } from '@/hooks/jobStatus'
import { cn } from '@/lib/utils'

export interface BaseWorkRecord {
  id: string
  status: string
  progress_pct?: number
  error_message?: string
  display_name?: string
  createdAt?: string
}

export interface WorkViewShellProps<T extends BaseWorkRecord> {
  backPath: string
  backLabel: string
  defaultName: string
  loadingLabel: string
  record: T | null
  loading: boolean
  pollError: string | null
  statusConfig: JobStatusConfig
  activeStatuses: string[]
  onSaveName: (newName: string) => Promise<void>
  onRetry?: () => Promise<void>
  retryLabel?: string
  retryStatuses?: string[]
  headerBadges?: React.ReactNode
  children: (record: T) => React.ReactNode
}

const WorkRetrySection = ({
  errorMessage,
  canWrite,
  retryLabel,
  onRetry,
}: {
  errorMessage?: string
  canWrite: boolean
  retryLabel: string
  onRetry: () => Promise<void>
}) => {
  const [retrying, setRetrying] = useState(false)
  const handleRetryClick = async () => {
    setRetrying(true)
    try {
      await onRetry()
    } catch {
      return
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="space-y-3">
      {errorMessage && <ErrorDisplay error={errorMessage} size="md" />}
      {canWrite && (
        <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetryClick} disabled={retrying}>
          {retrying ? 'Retrying...' : retryLabel}
        </Button>
      )}
    </div>
  )
}

export const WorkViewShell = <T extends BaseWorkRecord>(props: WorkViewShellProps<T>) => {
  const { backPath, backLabel, defaultName, loadingLabel, record, loading, pollError, statusConfig, activeStatuses, onSaveName, onRetry, retryLabel = 'Retry', retryStatuses = ['failed'], headerBadges, children } = props
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">{loadingLabel}</p>
      </div>
    )
  }

  if (pollError && !record) {
    return (
      <div className="space-y-4">
        <Button variant="link" icon={ArrowLeft} onClick={() => navigate(backPath)} className="text-sm">{backLabel}</Button>
        <ErrorDisplay error={pollError} size="md" />
      </div>
    )
  }

  if (!record) return null
  const isProcessing = activeStatuses.includes(record.status)
  const showRetry = Boolean(onRetry && retryStatuses.includes(record.status))

  return (
    <div className="space-y-6">
      <WorkPageHeader backPath={backPath} backLabel={backLabel} record={record} defaultName={defaultName} onSaveName={onSaveName} statusConfig={statusConfig} activeStatuses={activeStatuses}>{headerBadges}</WorkPageHeader>
      {isProcessing && record.progress_pct !== undefined && <ProgressBar progress={record.progress_pct} />}
      {showRetry && onRetry && <WorkRetrySection errorMessage={record.error_message} canWrite={canWrite} retryLabel={retryLabel} onRetry={onRetry} />}
      {children(record)}
    </div>
  )
}

export interface WorkCreateShellProps {
  backPath: string
  backLabel: string
  title: string
  subtitle: string
  error?: string | null
  actionIcon: LucideIcon
  actionLabel: string
  submittingLabel?: string
  submitting: boolean
  disabled: boolean
  onSubmit: () => void
  actionLeft?: React.ReactNode
  footerExtra?: React.ReactNode
  children: React.ReactNode
}

export const WorkCreateShell = ({
  backPath,
  backLabel,
  title,
  subtitle,
  error,
  actionIcon,
  actionLabel,
  submittingLabel = 'Starting...',
  submitting,
  disabled,
  onSubmit,
  actionLeft,
  footerExtra,
  children,
}: WorkCreateShellProps) => {
  const navigate = useNavigate()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Button variant="link" icon={ArrowLeft} onClick={() => navigate(backPath)} className="text-sm">
          {backLabel}
        </Button>
      </div>
      <div className="space-y-1">
        <h2 className="text-lg font-heading font-bold text-foreground">{title}</h2>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      {children}
      <ErrorDisplay error={error ?? null} />
      <div className="flex items-end justify-end gap-4">
        {actionLeft}
        <Button icon={actionIcon} onClick={onSubmit} disabled={disabled || submitting} className={cn('py-2.5', submitting && '[&_svg]:animate-spin')}>
          {submitting ? submittingLabel : actionLabel}
        </Button>
      </div>
      {footerExtra}
    </div>
  )
}

export const SelectedVideoPreview = ({
  videoUrl,
  videoFilename,
}: {
  videoUrl: string | null
  videoFilename?: string
}) => {
  if (!videoUrl) return null
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
        Selected Video
      </h3>
      <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border max-w-lg shadow-md">
        <video src={videoUrl} controls className="w-full h-full object-contain" />
      </div>
      {videoFilename && (
        <p className="text-sm text-foreground font-medium">{videoFilename}</p>
      )}
    </div>
  )
}

export const CheckboxOption = ({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  description: string
}) => (
  <label className="flex items-center gap-3 cursor-pointer group p-2.5 rounded-xl border border-transparent hover:border-border hover:bg-card/60 transition-all">
    <input
      type="checkbox"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
    />
    <div>
      <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
        {label}
      </span>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  </label>
)
