import { useState } from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { RecordUnavailable } from '@/components/shared/timeline'
import { ProcessingView } from './workspace/ProcessingView'
import { SceneWorkspace } from './workspace/SceneWorkspace'
import { useSceneAnalysisRecord } from './workspace/useSceneAnalysis'
import { WorkspaceHeader } from './workspace/WorkspaceHeader'

interface RecordViewProps {
  id: string
  onRetried: () => void
}

/** Polls the record; shows progress while the job runs and the workspace once it is completed. */
function RecordView({ id, onRetried }: RecordViewProps): JSX.Element {
  const { record, error } = useSceneAnalysisRecord(id)
  if (!record) return <RecordUnavailable error={error} loadingLabel="Loading analysis…" backTo="/scene-analysis" backLabel="Back to Scene Analysis" />
  if (record.status === 'completed') return <SceneWorkspace record={record} />
  return (
    <>
      <WorkspaceHeader record={record} />
      <ProcessingView record={record} onRetried={onRetried} />
    </>
  )
}

/** `/scene-analysis/:id` — full-width workspace for one scene analysis. */
export const SceneAnalysisWorkspacePage = () => {
  const { id } = useParams<{ id: string }>()
  // Bumped after a retry: remounting restarts the record polling from a fresh fetch.
  const [attempt, setAttempt] = useState(0)
  if (!id) return <Navigate to="/scene-analysis" replace />
  return (
    <div className="space-y-4 pb-12">
      <RecordView key={`${id}:${attempt}`} id={id} onRetried={() => setAttempt((n) => n + 1)} />
    </div>
  )
}
