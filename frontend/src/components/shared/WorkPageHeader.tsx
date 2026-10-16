import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { cn, getTimeAgo } from '@/lib/utils'
import { EditableNameField } from '@/components/shared/EditableNameField'

interface WorkPageHeaderProps {
  backPath: string
  backLabel: string
  record: { display_name?: string; createdAt?: string; status: string; progress_pct?: number; [key: string]: any }
  defaultName: string
  nameField?: string
  onSaveName: (newName: string) => Promise<void>
  statusConfig: Record<string, { label: string; color: string }>
  activeStatuses: string[]
  children?: React.ReactNode
}

export const WorkPageHeader = ({
  backPath,
  backLabel,
  record,
  defaultName,
  nameField = 'source_filename',
  onSaveName,
  statusConfig,
  activeStatuses,
  children,
}: WorkPageHeaderProps) => {
  const navigate = useNavigate()
  const statusCfg = statusConfig[record.status] || statusConfig.pending || { label: record.status, color: 'text-slate-500' }
  const isProcessing = activeStatuses.includes(record.status)

  return (
    <>
      <div className="flex items-center justify-between">
        <Button
          variant="link"
          icon={ArrowLeft}
          onClick={() => navigate(backPath)}
          className="text-sm"
        >
          {backLabel}
        </Button>
        {record.createdAt && (
          <span className="text-xs text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
        )}
      </div>

      <div className="space-y-2">
        <EditableNameField
          value={record.display_name || record[nameField] || ''}
          onSave={onSaveName}
          defaultText={defaultName}
        />
        <div className="flex items-center gap-2">
          <span className={cn("text-sm font-medium", statusCfg.color)}>{statusCfg.label}</span>
          {isProcessing && record.progress_pct !== undefined && (
            <span className="text-xs text-muted-foreground">({record.progress_pct}%)</span>
          )}
        </div>
        {children && (
          <div className="flex items-center gap-1.5">
            {children}
          </div>
        )}
      </div>
    </>
  )
}
