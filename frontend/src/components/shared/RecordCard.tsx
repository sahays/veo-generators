import { Archive, Film, Upload, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn, getTimeAgo } from '@/lib/utils'
import {
  UNIFIED_STATUS_LABELS,
  UNIFIED_STATUS_STYLES,
  formatElapsedDuration,
} from '@/hooks/jobStatus'
import { StatusBadge } from '@/components/shared/StatusBadge'

export const VideoSourceBadge = ({ source }: { source: 'production' | 'upload' }) => (
  <span
    className={cn(
      'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0',
      source === 'production'
        ? 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20'
        : 'bg-accent/10 text-accent-dark border-accent/20',
    )}
  >
    {source === 'production' ? (
      <span className="flex items-center gap-1">
        <Film size={8} /> Production
      </span>
    ) : (
      <span className="flex items-center gap-1">
        <Upload size={8} /> Upload
      </span>
    )}
  </span>
)

export interface CardMetadataFooterProps {
  createdAt?: string | number
  completedAt?: string
  durationSec?: number
  costUsd?: number
  extraMeta?: React.ReactNode
  leftContent?: React.ReactNode
  showArchive?: boolean
  onArchive?: (e: React.MouseEvent) => void
}

export const CardMetadataFooter = ({
  createdAt,
  completedAt,
  durationSec,
  costUsd,
  extraMeta,
  leftContent,
  showArchive,
  onArchive,
}: CardMetadataFooterProps) => {
  const elapsed =
    typeof createdAt === 'string'
      ? formatElapsedDuration(createdAt, completedAt)
      : null

  return (
    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
      <div className="flex items-center gap-2 flex-wrap">
        {leftContent}
        {createdAt !== undefined && <span>{getTimeAgo(createdAt)}</span>}
        {durationSec ? (
          <>
            <span className="text-muted-foreground/50">&middot;</span>
            <span>{Math.round(durationSec)}s</span>
          </>
        ) : elapsed ? (
          <>
            <span className="text-muted-foreground/50">&middot;</span>
            <span>{elapsed}</span>
          </>
        ) : null}
        {costUsd && costUsd > 0 ? (
          <>
            <span className="text-muted-foreground/50">&middot;</span>
            <span>${costUsd.toFixed(3)}</span>
          </>
        ) : null}
        {extraMeta}
      </div>
      {showArchive && onArchive && (
        <Button
          variant="unstyled"
          onClick={onArchive}
          className="p-1 -m-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
          title="Archive"
        >
          <Archive size={12} />
        </Button>
      )}
    </div>
  )
}

export interface RecordCardProps {
  onClick: () => void
  title: string
  titleRight?: React.ReactNode
  description?: string
  status?: string
  statusIcon?: LucideIcon
  statusLabels?: Record<string, string>
  statusStyles?: Record<string, string>
  progressPct?: number
  activeStatuses?: string[]
  badges?: React.ReactNode
  topMedia?: React.ReactNode
  sideMedia?: React.ReactNode
  children?: React.ReactNode
  footerProps: CardMetadataFooterProps
  className?: string
}

export const RecordCard = ({
  onClick,
  title,
  titleRight,
  description,
  status,
  statusIcon,
  statusLabels = UNIFIED_STATUS_LABELS,
  statusStyles = UNIFIED_STATUS_STYLES,
  progressPct,
  activeStatuses,
  badges,
  topMedia,
  sideMedia,
  children,
  footerProps,
  className,
}: RecordCardProps) => {
  const content = (
    <>
      {(status || badges || titleRight) && (
        <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
          {status && statusIcon && (
            <StatusBadge
              status={status}
              statusStyles={statusStyles}
              statusLabels={statusLabels}
              icon={statusIcon}
              progress={progressPct}
              activeStatuses={activeStatuses}
            />
          )}
          {badges}
          {titleRight && <div className="ml-auto">{titleRight}</div>}
        </div>
      )}

      <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-1.5">
        {title}
      </h4>

      {description && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">
          {description}
        </p>
      )}

      {children}

      <CardMetadataFooter {...footerProps} />
    </>
  )

  return (
    <Button
      variant="unstyled"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className={cn(
        'glass card-interactive bg-card rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full',
        topMedia ? 'overflow-hidden' : sideMedia ? 'p-4 flex gap-4' : 'p-5',
        className,
      )}
    >
      {topMedia ? (
        <>
          {topMedia}
          <div className="p-4">{content}</div>
        </>
      ) : sideMedia ? (
        <>
          {sideMedia}
          <div className="flex-1 min-w-0">{content}</div>
        </>
      ) : (
        content
      )}
    </Button>
  )
}
