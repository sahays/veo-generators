/**
 * The contract between a feature route module and the server.
 *
 * To add a feature: export a `StubFeature` from `routes/<feature>.ts` and list
 * it in `routes/index.ts`. `routes/sceneAnalysis.ts` and `routes/engagement.ts` are complete examples.
 */
import type { InsightUsage } from '../../../src/types/insights.ts'
import type { Route } from './router.ts'

export interface StubFeature {
  /** Pricing feature id, as used in `GET /api/v1/pricing/usage/{feature}/{id}` (e.g. `scene_analysis`). */
  name: string
  routes: readonly Route[]
  /** Restores this feature's seed state (`POST /__stub/reset`). */
  reset: () => void
  /** Usage of one record for the "Services Used" panel; undefined when the record does not exist. */
  usage?: (recordId: string) => InsightUsage | undefined
}
