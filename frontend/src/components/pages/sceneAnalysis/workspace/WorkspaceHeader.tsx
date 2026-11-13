import { Clock, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ModelPill } from '@/components/ModelPill'
import { VideoSourceBadge } from '@/components/shared/RecordCard'
import { RecordHeader, RecordStatusPill } from '@/components/shared/timeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/hooks/useApiClient'
import { getTimeAgo } from '@/lib/utils'
import { useAuthStore } from '@/store/useAuthStore'
import type { SceneAnalysisRecord } from '@/types/insights'
import { formatTimecode } from '@/types/timeline/timeFormat'

/** Name shown for a record: the user's name, else the detected title, else the file name. */
export function recordName(record: SceneAnalysisRecord): string {
  return record.display_name || record.content_title || record.video_filename || 'Untitled video'
}

function RecordBadges({ record }: { record: SceneAnalysisRecord }): JSX.Element {
  return (
    <>
      <RecordStatusPill status={record.status} />
      <VideoSourceBadge source={record.source_type} />
      <ModelPill modelName={record.usage?.model_name || record.model_id || undefined} />
      {record.duration_sec > 0 && (
        <Badge>
          <Clock size={10} aria-hidden /> {formatTimecode(record.duration_sec)}
        </Badge>
      )}
      {record.focus && <Badge variant="outline" title={`Focus: ${record.focus}`}>Focus: {record.focus}</Badge>}
      <span className="text-[11px] text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
    </>
  )
}

/** Link to start an Engagement analysis on this scene analysis (it is reused, never re-run). */
export function RunEngagementButton({ analysisId }: { analysisId: string }): JSX.Element | null {
  const canWrite = useAuthStore((state) => state.isMaster || state.isPower)
  if (!canWrite) return null
  return (
    <Button asChild variant="primary" size="sm">
      <Link to={`/engagement/new?analysis=${encodeURIComponent(analysisId)}`} data-testid="run-engagement">
        <TrendingUp size={14} aria-hidden /> Run Engagement
      </Link>
    </Button>
  )
}

export interface WorkspaceHeaderProps {
  record: SceneAnalysisRecord
  /** Buttons on the right (Run Engagement, Export). */
  actions?: React.ReactNode
}

/** Back link, editable name, status / source / model badges and the page actions. */
export function WorkspaceHeader({ record, actions }: WorkspaceHeaderProps): JSX.Element {
  return (
    <RecordHeader
      backTo="/scene-analysis"
      backLabel="Back to Scene Analysis"
      name={recordName(record)}
      onRename={(name) => api.sceneAnalysis.update(record.id, { display_name: name })}
      badges={<RecordBadges record={record} />}
      actions={actions}
    />
  )
}
