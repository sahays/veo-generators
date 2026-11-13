import { api } from '@/hooks/useApiClient'
import { useAsyncResource, type AsyncResource } from '@/hooks/timeline/useAsyncResource'
import { usePolling } from '@/hooks/usePolling'
import type { SceneAnalysisRecord, TimelineResponse } from '@/types/insights'

/** Statuses during which the worker is still running and the record is polled. */
export const ACTIVE_STATUSES = ['pending', 'analyzing', 'processing']
const POLL_INTERVAL_MS = 3000

/** The record, polled while the job runs. */
export function useSceneAnalysisRecord(id: string): { record: SceneAnalysisRecord | null; loading: boolean; error: string | null } {
  return usePolling<SceneAnalysisRecord>(id, api.sceneAnalysis.get, ACTIVE_STATUSES, POLL_INTERVAL_MS)
}

/** `timeline.json` plus the filmstrip description, fetched once the analysis is completed. */
export function useSceneTimeline(id: string): AsyncResource<TimelineResponse> {
  return useAsyncResource(() => api.sceneAnalysis.timeline(id), id, 'Could not load the timeline')
}
