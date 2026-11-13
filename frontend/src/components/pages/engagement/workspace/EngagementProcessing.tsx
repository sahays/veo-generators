import { ScanSearch } from 'lucide-react'
import { Link } from 'react-router-dom'
import { JobProgress, JobRetryPanel, type JobStage } from '@/components/shared/timeline'
import { Button } from '@/components/ui/button'
import { api } from '@/hooks/useApiClient'
import type { EngagementRecord } from '@/types/insights'

/** `stage` of a job that cannot start until the scene analysis of its video is completed. */
const WAITING_STAGE = 'waiting'

/** Stages in order (contract section 5). `waiting` comes first: a job only runs on a completed scene analysis. */
const STAGES: JobStage[] = [
  { key: WAITING_STAGE, label: 'Scene analysis', hint: 'The video is analysed first' },
  { key: 'signal', label: 'Signal', hint: 'Building the engagement curve' },
  { key: 'stats', label: 'Statistics', hint: 'Peaks, valleys, drops and drivers' },
  { key: 'explain', label: 'Explanations', hint: 'Describing each moment' },
  { key: 'recommend', label: 'Recommendations', hint: 'Writing recommendations' },
]

function SceneAnalysisLink({ analysisId, label }: { analysisId: string; label: string }): JSX.Element {
  return (
    <Button asChild variant="outline" size="sm">
      <Link to={`/scene-analysis/${encodeURIComponent(analysisId)}`} data-testid="scene-analysis-link">
        <ScanSearch size={14} aria-hidden /> {label}
      </Link>
    </Button>
  )
}

function WaitingNote({ analysisId }: { analysisId: string }): JSX.Element {
  return (
    <div data-testid="waiting-on-analysis" className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/30 p-3">
      <p className="min-w-0 flex-1 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">Waiting for the scene analysis of this video.</span> The engagement report starts by itself as soon as the analysis is finished; you can leave this page.
      </p>
      <SceneAnalysisLink analysisId={analysisId} label="Open the scene analysis" />
    </div>
  )
}

export interface EngagementProcessingProps {
  record: EngagementRecord
  /** Called after a successful retry request so the page can start polling again. */
  onRetried: () => void
}

/** Stage stepper while the job runs or waits; the error with Retry when it failed. */
export function EngagementProcessing({ record, onRetried }: EngagementProcessingProps): JSX.Element {
  const failed = record.status === 'failed'
  const waiting = !failed && record.stage === WAITING_STAGE
  return (
    <JobProgress
      ariaLabel="Engagement analysis progress"
      stages={STAGES}
      activeStage={record.stage}
      failed={failed}
      detail={record.stage_detail}
      progressPct={record.progress_pct}
      statusText={waiting ? 'Not started yet: waiting for the scene analysis' : undefined}
    >
      {waiting && <WaitingNote analysisId={record.scene_analysis_id} />}
      {failed && (
        <JobRetryPanel
          error={record.error_message || 'The engagement analysis failed.'}
          retryLabel="Retry"
          onRetry={() => api.engagement.retry(record.id)}
          onRetried={onRetried}
          hint="A retry reuses the scene analysis and the steps that already finished."
        />
      )}
    </JobProgress>
  )
}
