import type { Project } from '@/types/project'
import type { StoryGraphStageRun } from '@/types/storygraph'
import type { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import type { StageRenderQuality } from './pipelineStages'

export type StudioProjectsApi = ReturnType<typeof useAdsProjectActions>['projects']

type GraphLoader = (id: string) => Promise<Project>
type RunMatcher = (run: StoryGraphStageRun) => boolean

const POLL_INTERVAL_MS = 5000
const MAX_POLLS = 180
/** Tolerated browser/server clock skew when matching runs newer than a request. */
const CLOCK_SKEW_MS = 5000
const TIMEOUT_RE = /timed out|504|Server Components render|fetch failed/i

/** True when an error looks like a proxy/server-action timeout while work continues server-side. */
export function isRecoverableTimeout(err: unknown): boolean {
  return TIMEOUT_RE.test(err instanceof Error ? err.message : String(err))
}

async function pollUntilRunSettles(
  getStoryGraph: GraphLoader,
  productionId: string,
  label: string,
  matches: RunMatcher,
  onGraphUpdated: (snapshot: Project) => void,
): Promise<Project> {
  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
    const snap = await getStoryGraph(productionId).catch(() => null)
    if (!snap) continue
    onGraphUpdated(snap)
    const runs = (snap.story_graph?.stage_runs || []).filter(matches)
    const latest = runs[runs.length - 1]
    if (latest?.status === 'failed' || latest?.error) {
      throw new Error(latest.error || `Stage ${label} failed on server`)
    }
    if (latest?.completed) return snap
  }
  throw new Error(`Stage ${label} timed out after extended background polling`)
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
    return (await projectsApi.runStage(productionId, stageId, force, quality)) as Project
  } catch (err) {
    if (!isRecoverableTimeout(err)) throw err
    return await pollUntilRunSettles(
      projectsApi.getStoryGraph, productionId, stageId, (sr) => sr.stage === stageId, onGraphUpdated,
    )
  }
}

/**
 * Run a long request that records a `stageId` StageRun (e.g. S8_REPAIR). On timeout,
 * poll until a run of that stage created after the request started completes or fails.
 * Returns the direct response, or `null` when recovered via polling (snapshot already pushed).
 */
export async function runStageRequestWithRecovery<T>(
  projectsApi: StudioProjectsApi,
  productionId: string,
  stageId: string,
  call: () => Promise<T>,
  onGraphUpdated: (snapshot: Project) => void,
): Promise<T | null> {
  const since = Date.now() - CLOCK_SKEW_MS
  try {
    return await call()
  } catch (err) {
    if (!isRecoverableTimeout(err)) throw err
    const isNewer: RunMatcher = (sr) =>
      sr.stage === stageId && Date.parse(sr.created_at ?? '') >= since
    await pollUntilRunSettles(projectsApi.getStoryGraph, productionId, stageId, isNewer, onGraphUpdated)
    return null
  }
}
