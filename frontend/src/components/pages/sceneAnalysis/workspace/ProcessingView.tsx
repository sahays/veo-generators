import { JobProgress, JobRetryPanel, type JobStage } from '@/components/shared/timeline'
import { api } from '@/hooks/useApiClient'
import type { SceneAnalysisRecord } from '@/types/insights'

/** Worker stages in order (contract section 5). */
const STAGES: JobStage[] = [
  { key: 'probe', label: 'Probing video', hint: 'Reading duration and detecting cuts' },
  { key: 'analyze', label: 'Analysing', hint: 'Gemini reads the video window by window' },
  { key: 'merge', label: 'Merging', hint: 'Combining windows into one timeline' },
  { key: 'filmstrip', label: 'Thumbnails', hint: 'Building the filmstrip' },
]

export interface ProcessingViewProps {
  record: SceneAnalysisRecord
  /** Called after a successful retry request so the page can start polling again. */
  onRetried: () => void
}

/** Stage stepper with progress while the job runs; error and retry when it failed. */
export function ProcessingView({ record, onRetried }: ProcessingViewProps): JSX.Element {
  const failed = record.status === 'failed'
  return (
    <JobProgress
      ariaLabel="Analysis progress"
      stages={STAGES}
      activeStage={record.stage}
      failed={failed}
      detail={record.stage_detail}
      progressPct={record.progress_pct}
      statusExtra={record.window_count > 1 ? ` · ${record.window_count} windows` : ''}
    >
      {failed && (
        <JobRetryPanel
          error={record.error_message || 'The analysis failed.'}
          retryLabel="Retry analysis"
          onRetry={() => api.sceneAnalysis.retry(record.id)}
          onRetried={onRetried}
          hint="A retry reuses the windows that were already analysed."
        />
      )}
    </JobProgress>
  )
}
