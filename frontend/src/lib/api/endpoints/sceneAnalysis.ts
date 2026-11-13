import type {
  ProductionItem,
  UploadItem,
} from '@/components/shared/VideoSourceSelector'
import type {
  SceneAnalysisCreate,
  SceneAnalysisRecord,
  SceneAnalysisStatus,
  TimelineResponse,
} from '@/types/insights'
import { createCrudClient } from '../core/_crud'
import { API_BASE_URL, buildQS, postJson, request } from '../core/_http'

const BASE = `${API_BASE_URL}/scene-analysis`

const sceneAnalysisCrud = createCrudClient<SceneAnalysisRecord>(
  BASE,
  'scene analysis record',
)

export const sceneAnalysis = {
  ...sceneAnalysisCrud,
  list: (params?: { archived?: boolean }) =>
    sceneAnalysisCrud.list(buildQS({ archived: params?.archived })),
  // The video is named by id; the server resolves the gs:// URI itself.
  create: (data: SceneAnalysisCreate) =>
    postJson<{ id: string; status: SceneAnalysisStatus }>(
      BASE,
      data,
      'Failed to start scene analysis',
    ),
  // 409 until the analysis is completed.
  timeline: (id: string) =>
    request<TimelineResponse>(
      `${BASE}/${id}/timeline`,
      'Failed to load scene analysis timeline',
    ),
  listUploadSources: () =>
    request<UploadItem[]>(
      `${BASE}/sources/uploads`,
      'Failed to list upload sources',
    ),
  listProductionSources: () =>
    request<ProductionItem[]>(
      `${BASE}/sources/productions`,
      'Failed to list production sources',
    ),
}
