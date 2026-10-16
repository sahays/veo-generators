import { useState, useEffect } from 'react'
import { Cpu, Globe } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface AIModel {
  id: string
  name: string
  code: string
  provider: string
  capability: string
  regions: string[]
  is_default: boolean
  is_active: boolean
}

interface ModelRegionPickerProps {
  capability: 'text' | 'image' | 'video'
  value: { modelId?: string; region?: string }
  onChange: (val: { modelId?: string; region?: string }) => void
  label?: string
  className?: string
}

const FALLBACK_DEFAULTS: Record<
  'text' | 'image' | 'video',
  { name: string; code: string; region: string }
> = {
  text: { name: 'Gemini 3.8 Flash', code: 'gemini-3.8-flash', region: 'global' },
  image: { name: 'Gemini Nano Banana 2.1', code: 'gemini-nano-banana-2.1', region: 'global' },
  video: { name: 'Gemini Omni 1.1 Flash', code: 'gemini-omni-1.1-flash-preview', region: 'global' },
}

// Shared cache so multiple pickers don't re-fetch
let _modelsCache: AIModel[] | null = null
let _defaultsCache: Record<string, any> | null = null

export const ModelRegionPicker = ({ capability, value, onChange, label, className }: ModelRegionPickerProps) => {
  const fallback = FALLBACK_DEFAULTS[capability]
  const [modelName, setModelName] = useState<string>(fallback.name)
  const [region, setRegion] = useState<string>(fallback.region)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        if (!_modelsCache || !_defaultsCache) {
          const [m, d] = await Promise.all([
            api.models.list(),
            api.models.defaults(),
          ])
          _modelsCache = m
          _defaultsCache = d
        }
        if (cancelled) return

        const activeModels = (_modelsCache || []).filter(
          m => m.capability === capability && m.is_active
        )
        const defaultEntry = _defaultsCache?.[capability]
        const matchedModel =
          activeModels.find(m => m.code === defaultEntry?.code) ||
          activeModels.find(m => m.is_default) ||
          activeModels[0]

        const resolvedCode = defaultEntry?.code || matchedModel?.code || fallback.code
        const resolvedName = defaultEntry?.name || matchedModel?.name || fallback.name
        const resolvedRegion =
          defaultEntry?.region ||
          matchedModel?.regions?.[0] ||
          fallback.region

        setModelName(resolvedName)
        setRegion(resolvedRegion)

        if (value.modelId !== resolvedCode || value.region !== resolvedRegion) {
          onChange({
            modelId: resolvedCode,
            region: resolvedRegion,
          })
        }
      } catch (e) {
        console.error('Failed to load model defaults:', e)
        if (!cancelled && (!value.modelId || !value.region)) {
          onChange({
            modelId: fallback.code,
            region: fallback.region,
          })
        }
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [capability]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={cn("flex items-end gap-3", className)}>
      {label && (
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider shrink-0 pb-2.5">
          {label}
        </span>
      )}
      <div className="space-y-1.5">
        <span className="block text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">
          Model
        </span>
        <div
          className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg bg-muted/50 border border-border text-xs font-medium text-foreground whitespace-nowrap"
          title={`Default ${capability} model (${value.modelId || fallback.code})`}
        >
          <Cpu size={13} className="text-accent-dark shrink-0" />
          <span>{modelName}</span>
        </div>
      </div>
      <div className="space-y-1.5">
        <span className="block text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">
          Region
        </span>
        <div
          className="inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg bg-muted/50 border border-border text-xs font-mono font-medium text-foreground whitespace-nowrap"
          title="Default Gemini / Vertex AI region"
        >
          <Globe size={13} className="text-accent-dark shrink-0" />
          <span>{region}</span>
        </div>
      </div>
    </div>
  )
}

/** Invalidate the shared cache (e.g., after editing models) */
export const invalidateModelCache = () => {
  _modelsCache = null
  _defaultsCache = null
}
