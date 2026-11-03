import type { useAdsProjectActions } from '../../projects/useAdsProjectActions'

/** Projects API surface used by the studio run commands. */
export type StudioProjectsApi = ReturnType<typeof useAdsProjectActions>['projects']
