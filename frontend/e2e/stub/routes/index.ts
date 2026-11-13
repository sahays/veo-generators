/**
 * The stub's route table. EXTENSION POINT: add a feature module to `FEATURES`
 * and its routes, reset hook and usage lookup are picked up automatically.
 */
import type { StubFeature } from '../lib/feature.ts'
import type { Route } from '../lib/router.ts'
import { coreRoutes } from './core.ts'
import { engagementFeature } from './engagement.ts'
import { sceneAnalysisFeature } from './sceneAnalysis.ts'
import { uploadsFeature } from './uploads.ts'

/** Order matters for `reset`: the engagement seeds link to seeded scene analyses. */
export const FEATURES: readonly StubFeature[] = [sceneAnalysisFeature, engagementFeature, uploadsFeature]

export const ROUTES: readonly Route[] = [
  ...coreRoutes(FEATURES),
  ...FEATURES.flatMap((feature) => feature.routes),
]
