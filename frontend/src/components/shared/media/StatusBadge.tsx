import { type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatusBadgeProps {
  status: string
  statusStyles: Record<string, string>
  statusLabels: Record<string, string>
  icon: LucideIcon
  progress?: number
  activeStatuses?: string[]
}

export const StatusBadge = ({
  status,
  statusStyles,
  statusLabels,
  icon: Icon,
  progress,
  activeStatuses,
}: StatusBadgeProps) => {
  const showProgress = activeStatuses && progress !== undefined && activeStatuses.includes(status)

  return (
    <div className="flex items-center gap-1.5">
      <span className={cn(
        "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0",
        statusStyles[status] || statusStyles.pending
      )}>
        <Icon size={10} />
        {statusLabels[status] || status}
      </span>
      {showProgress && (
        <span className="text-[9px] text-muted-foreground">{progress}%</span>
      )}
    </div>
  )
}
