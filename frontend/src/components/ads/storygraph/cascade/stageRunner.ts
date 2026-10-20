import type { Project } from '@/types/project'
import type { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import type { StageRenderQuality } from './pipelineStages'

export type StudioProjectsApi = ReturnType<typeof useAdsProjectActions>['projects']

async function pollStageUntilDone(
  getStoryGraph: (id: string) => Promise<Project>,
  productionId: string,
  stageId: string,
  onGraphUpdated: (snapshot: Project) => void,
): Promise<Project> {
  for (let i = 0; i < 180; i++) {
    await new Promise((r) => setTimeout(r, 5000))
    const snap = await getStoryGraph(productionId).catch(() => null)
    if (!snap) continue
    onGraphUpdated(snap)
    const runs = (snap.story_graph?.stage_runs || []).filter((sr) => sr.stage === stageId)
    const latest = runs[runs.length - 1]
    if (latest?.status === 'failed' || latest?.error) {
      throw new Error(latest.error || `Stage ${stageId} failed on server`)
    }
    if (latest?.completed) return snap
  }
  throw new Error(`Stage ${stageId} timed out after extended background polling`)
}

/** Run one stage; on proxy timeouts fall back to polling the snapshot until it settles. */
export async function runStageWithRecovery(
  projectsApi: StudioProjectsApi,
  productionId: string,
  stageId: string,
  force: boolean,
  onGraphUpdated: (snapshot: Project) => void,
  quality?: StageRenderQuality,
): Promise<Project> {
  try {
    return (await projectsApi.runStage(
      productionId,
      stageId,
      force,
      quality,
    )) as unknown as Project
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    if (/timed out|504|Server Components render|fetch failed/i.test(msg)) {
      return await pollStageUntilDone(projectsApi.getStoryGraph, productionId, stageId, onGraphUpdated)
    }
    throw err
  }
}
