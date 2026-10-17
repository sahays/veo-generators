import type { Project } from '@/types/project'
import { createCrudClient } from './_crud'
import {
  API_BASE_URL,
  buildQS,
  jsonInit,
  patchJson,
  postJson,
  request,
  requestVoid,
} from './_http'

const projectsCrud = createCrudClient<any>(`${API_BASE_URL}/productions`, 'production')

export const projects = {
  list: (params?: { archived?: boolean; mine?: boolean }) =>
    projectsCrud.list(buildQS({ archived: params?.archived, mine: params?.mine })),
  get: projectsCrud.get,
  create: (project: any) =>
    postJson<any>(`${API_BASE_URL}/productions`, project, 'Failed to create production'),
  update: (id: string, updates: Record<string, any>) =>
    patchJson(`${API_BASE_URL}/productions/${id}`, updates, 'Failed to update production'),
  updateScene: (id: string, sceneId: string, updates: Record<string, any>) =>
    requestVoid(
      `${API_BASE_URL}/productions/${id}/scenes/${sceneId}`,
      'Failed to update scene',
      jsonInit('PATCH', updates),
    ),
  analyze: (
    id: string,
    prompt_id?: string,
    schema_id?: string,
    model_id?: string,
    region?: string,
    overrides?: Record<string, any>,
  ) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/analyze`,
      { prompt_id, schema_id, model_id, region, ...(overrides || {}) },
      'Analysis failed',
    ),
  buildPrompt: (id: string, sceneId: string) =>
    request<any>(
      `${API_BASE_URL}/productions/${id}/scenes/${sceneId}/build-prompt`,
      'Build prompt failed',
      { method: 'POST' },
    ),
  generateFrame: (id: string, sceneId: string, promptData?: any) => {
    const init: RequestInit = promptData
      ? jsonInit('POST', { prompt_data: promptData })
      : { method: 'POST' }
    return request<any>(
      `${API_BASE_URL}/productions/${id}/scenes/${sceneId}/frame`,
      'Frame generation failed',
      init,
    )
  },
  generateSceneVideo: (id: string, sceneId: string, promptData?: any) => {
    const init: RequestInit = promptData
      ? jsonInit('POST', { prompt_data: promptData })
      : { method: 'POST' }
    return request<any>(
      `${API_BASE_URL}/productions/${id}/scenes/${sceneId}/video`,
      'Video generation failed',
      init,
    )
  },
  checkOperation: (operationName: string, productionId?: string, sceneId?: string) => {
    const qs = buildQS({ production_id: productionId, scene_id: sceneId })
    return request<any>(
      `${API_BASE_URL}/diagnostics/operations/${operationName}${qs ? `?${qs}` : ''}`,
      'Operation check failed',
    )
  },
  render: (
    id: string,
    options?: {
      quality?: 'draft' | 'final'
      resolution?: '360p' | '720p' | '1080p'
      auto_review?: boolean
      auto_eval?: boolean
      max_eval_iterations?: number
    },
  ) =>
    postJson<{ status: string }>(
      `${API_BASE_URL}/productions/${id}/render`,
      options || {},
      'Render failed',
    ),
  reviewStoryboard: (id: string) =>
    postJson<Project>(
      `${API_BASE_URL}/productions/${id}/review`,
      {},
      'Storyboard review failed',
    ),
  evaluateVideo: (id: string) =>
    postJson<Project>(
      `${API_BASE_URL}/productions/${id}/evaluate`,
      {},
      'Video evaluation failed',
    ),
  regenerateFlagged: (id: string) =>
    postJson<{ status: string }>(
      `${API_BASE_URL}/productions/${id}/regenerate-flagged`,
      {},
      'Regenerate flagged scenes failed',
    ),
  stitch: (id: string) =>
    request<any>(`${API_BASE_URL}/productions/${id}/stitch`, 'Stitch failed', {
      method: 'POST',
    }),
  checkStitchStatus: (id: string) =>
    request<any>(
      `${API_BASE_URL}/productions/${id}/stitch-status`,
      'Stitch status check failed',
    ),
  getStoryGraph: (id: string) =>
    request<any>(
      `${API_BASE_URL}/productions/${id}/graph`,
      'Failed to load story graph',
    ),
  runStoryGraph: (
    id: string,
    options?: { auto_approve_gates?: boolean; story_text?: string },
  ) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/run`,
      options || {},
      'Failed to run StoryGraph pipeline',
    ),
  runStage: (id: string, stageId: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/stages/${stageId}/run`,
      {},
      `Failed to run stage ${stageId}`,
    ),
  approveGate: (id: string, gateId: 'G1' | 'G2' | 'G3', notes?: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/gates/${gateId}/approve`,
      { reviewer: 'studio_user', notes },
      `Failed to approve gate ${gateId}`,
    ),
  rejectGate: (id: string, gateId: 'G1' | 'G2' | 'G3', notes?: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/gates/${gateId}/reject`,
      { reviewer: 'studio_user', notes: notes || 'Revision requested' },
      `Failed to reject gate ${gateId}`,
    ),
  approveAppearance: (id: string, appearanceId: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/appearances/${appearanceId}/approve`,
      {},
      'Failed to approve appearance',
    ),
  regenerateAppearance: (id: string, appearanceId: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/appearances/${appearanceId}/regenerate`,
      {},
      'Failed to regenerate appearance',
    ),
  compileShot: (id: string, shotId: string) =>
    postJson<any>(
      `${API_BASE_URL}/productions/${id}/shots/${shotId}/compile`,
      {},
      'Failed to compile shot prompt',
    ),
  delete: projectsCrud.delete,
  archive: projectsCrud.archive,
  unarchive: projectsCrud.unarchive,
}
