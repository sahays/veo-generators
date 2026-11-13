import type {
  ProductionItem,
  UploadItem,
} from '@/components/shared/VideoSourceSelector'
import type {
  EngagementCreate,
  EngagementCreateResponse,
  EngagementRecord,
  EngagementReport,
  EngagementTemplate,
  InsightSourceType,
  SceneAnalysisStatus,
  SignalPreview,
} from '@/types/insights'
import { createCrudClient } from '../core/_crud'
import { API_BASE_URL, buildQS, postJson, request } from '../core/_http'

const BASE = `${API_BASE_URL}/engagement`

/** A scene analysis that an engagement job can reuse (`GET /sources/analyses`). */
export interface EngagementAnalysisSource {
  id: string
  display_name: string
  video_filename: string
  source_type: InsightSourceType
  source_id: string
  status: SceneAnalysisStatus
  duration_sec: number
  createdAt: string
  video_signed_url: string
}

const engagementCrud = createCrudClient<EngagementRecord>(
  BASE,
  'engagement record',
)

export const engagement = {
  ...engagementCrud,
  list: (params?: { archived?: boolean }) =>
    engagementCrud.list(buildQS({ archived: params?.archived })),
  // Exactly one of `scene_analysis_id`, or `source_type` + `source_id`.
  create: (data: EngagementCreate) =>
    postJson<EngagementCreateResponse>(
      BASE,
      data,
      'Failed to start engagement analysis',
    ),
  // 409 until the engagement job is completed.
  report: (id: string) =>
    request<EngagementReport>(
      `${BASE}/${id}/report`,
      'Failed to load engagement report',
    ),
  templates: () =>
    request<EngagementTemplate[]>(
      `${BASE}/templates`,
      'Failed to list engagement templates',
    ),
  // The server downloads and parses the uploaded BARC CSV.
  signalPreview: (uploadId: string) =>
    postJson<SignalPreview>(
      `${BASE}/signal-preview`,
      { upload_id: uploadId },
      'Failed to preview engagement signal',
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
  listAnalysisSources: () =>
    request<EngagementAnalysisSource[]>(
      `${BASE}/sources/analyses`,
      'Failed to list scene analysis sources',
    ),
}
