import { useMemo } from 'react'
import { api } from '../../../lib/api'

export function useAdsProjectActions() {
  return useMemo(
    () => ({
      projects: api.projects,
      system: api.system,
    }),
    [],
  )
}
