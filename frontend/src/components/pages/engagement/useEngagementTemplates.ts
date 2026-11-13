import { useEffect, useMemo, useState } from 'react'
import { api } from '@/hooks/useApiClient'
import type { EngagementTemplate } from '@/types/insights'

// The built-in templates are static server configuration, so one request serves every page.
let pending: Promise<EngagementTemplate[]> | null = null

function loadTemplates(): Promise<EngagementTemplate[]> {
  if (!pending) {
    pending = api.engagement.templates().catch((cause: unknown) => {
      pending = null
      throw cause
    })
  }
  return pending
}

export interface TemplatesState {
  templates: EngagementTemplate[]
  loading: boolean
  error: string | null
}

/** The built-in engagement templates (id, label, description, preview curve). */
export function useEngagementTemplates(): TemplatesState {
  const [state, setState] = useState<TemplatesState>({ templates: [], loading: true, error: null })
  useEffect(() => {
    let current = true
    loadTemplates()
      .then((templates) => current && setState({ templates, loading: false, error: null }))
      .catch((cause: unknown) => current && setState({ templates: [], loading: false, error: cause instanceof Error ? cause.message : 'Could not load the engagement templates' }))
    return () => {
      current = false
    }
  }, [])
  return state
}

/** Template labels by id, for signal badges. Empty until the templates have loaded. */
export function useTemplateLabels(): ReadonlyMap<string, string> {
  const { templates } = useEngagementTemplates()
  return useMemo(() => new Map(templates.map((template) => [template.id, template.label])), [templates])
}
