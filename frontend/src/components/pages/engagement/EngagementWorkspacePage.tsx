import { useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { RecordUnavailable } from '@/components/shared/timeline'
import { EngagementHeader } from './workspace/EngagementHeader'
import { EngagementProcessing } from './workspace/EngagementProcessing'
import { EngagementWorkspace } from './workspace/EngagementWorkspace'
import { useEngagementRecord } from './workspace/useEngagement'

interface ReportViewProps {
  id: string
  onRetried: () => void
}

/** Polls the record; shows the job's progress until it is completed, then the workspace. */
function ReportView({ id, onRetried }: ReportViewProps): JSX.Element {
  const { record, error } = useEngagementRecord(id)
  if (!record) return <RecordUnavailable error={error} loadingLabel="Loading engagement report…" backTo="/engagement" backLabel="Back to Engagement" />
  if (record.status === 'completed') return <EngagementWorkspace record={record} />
  return (
    <>
      <EngagementHeader record={record} />
      <EngagementProcessing record={record} onRetried={onRetried} />
    </>
  )
}

/** `/engagement/:id` — full-width workspace for one engagement report. */
export const EngagementWorkspacePage = () => {
  const { id } = useParams<{ id: string }>()
  // Bumped after a retry: remounting restarts the record polling from a fresh fetch.
  const [attempt, setAttempt] = useState(0)
  if (!id) return <Navigate to="/engagement" replace />
  return (
    <div className="space-y-4 pb-12">
      <ReportView key={`${id}:${attempt}`} id={id} onRetried={() => setAttempt((n) => n + 1)} />
    </div>
  )
}
