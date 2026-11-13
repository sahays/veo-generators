import { api } from '@/hooks/useApiClient'
import { useAsyncResource, type AsyncResource } from '@/hooks/timeline/useAsyncResource'
import { usePolling } from '@/hooks/usePolling'
import type { EngagementRecord, EngagementReport, TimelineResponse } from '@/types/insights'

/** Statuses during which the worker is still running (or waiting) and the record is polled. */
const ACTIVE_STATUSES = ['pending', 'processing']
const POLL_INTERVAL_MS = 3000

/** The record, polled while the job runs or waits for its scene analysis. */
export function useEngagementRecord(id: string): { record: EngagementRecord | null; loading: boolean; error: string | null } {
  return usePolling<EngagementRecord>(id, api.engagement.get, ACTIVE_STATUSES, POLL_INTERVAL_MS)
}

/** Everything a completed report is drawn from. */
export interface EngagementDocs {
  report: EngagementReport
  /** Timeline and filmstrip of the scene analysis the report was built on. */
  scene: TimelineResponse
}

/** `report.json` and the linked scene analysis timeline, fetched together once the job is completed. */
export function useEngagementDocs(record: EngagementRecord): AsyncResource<EngagementDocs> {
  const load = async (): Promise<EngagementDocs> => {
    const [report, scene] = await Promise.all([api.engagement.report(record.id), api.sceneAnalysis.timeline(record.scene_analysis_id)])
    return { report, scene }
  }
  return useAsyncResource(load, record.id, 'Could not load the engagement report')
}
