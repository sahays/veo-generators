import { useState, useEffect } from 'react'
import { Cpu, Globe } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
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

interface DefaultModelEntry {
  code?: string
  name?: string
  region?: string
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
let _defaultsCache: Record<string, DefaultModelEntry> | null = null

async function fetchCachedModels() {
  if (!_modelsCache || !_defaultsCache) {
    const [m, d] = await Promise.all([api.models.list(), api.models.defaults()])
    _modelsCache = m
    _defaultsCache = d as Record<string, DefaultModelEntry>
  }
  return { models: _modelsCache || [], defaults: _defaultsCache || {} }
}

function resolveModelSelection(
  capability: 'text' | 'image' | 'video',
  models: AIModel[],
  defaults: Record<string, DefaultModelEntry>,
) {
  const fallback = FALLBACK_DEFAULTS[capability]
  const activeModels = models.filter((m) => m.capability === capability && m.is_active)
  const defaultEntry = defaults[capability]
  const matched =
    activeModels.find((m) => m.code === defaultEntry?.code) ||
    activeModels.find((m) => m.is_default) ||
    activeModels[0]

  return {
    code: defaultEntry?.code || matched?.code || fallback.code,
    name: defaultEntry?.name || matched?.name || fallback.name,
    region: defaultEntry?.region || matched?.regions?.[0] || fallback.region,
  }
}

const PickerBadge = ({
  heading,
  icon: Icon,
  text,
  title,
  mono,
}: {
  heading: string
  icon: typeof Cpu
  text: string
  title: string
  mono?: boolean
}) => (
  <div className="space-y-1.5">
    <span className="block text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">
      {heading}
    </span>
    <div
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-2.5 rounded-lg bg-muted/50 border border-border text-xs font-medium text-foreground whitespace-nowrap',
        mono && 'font-mono',
      )}
      title={title}
    >
      <Icon size={13} className="text-accent-dark shrink-0" />
      <span>{text}</span>
    </div>
  </div>
)

function useModelRegionResolution(
  capability: 'text' | 'image' | 'video',
  value: { modelId?: string; region?: string },
  onChange: (val: { modelId?: string; region?: string }) => void,
) {
  const fallback = FALLBACK_DEFAULTS[capability]
  const [modelName, setModelName] = useState<string>(fallback.name)
  const [region, setRegion] = useState<string>(fallback.region)

  useEffect(() => {
    let cancelled = false
    fetchCachedModels()
      .then(({ models, defaults }) => {
        if (cancelled) return
        const resolved = resolveModelSelection(capability, models, defaults)
        setModelName(resolved.name)
        setRegion(resolved.region)
        if (value.modelId !== resolved.code || value.region !== resolved.region) {
          onChange({ modelId: resolved.code, region: resolved.region })
        }
      })
      .catch(() => {
        if (!cancelled && (!value.modelId || !value.region)) {
          onChange({ modelId: fallback.code, region: fallback.region })
        }
      })
    return () => { cancelled = true }
  }, [capability]) // eslint-disable-line react-hooks/exhaustive-deps

  return { modelName, region, fallback }
}

export const ModelRegionPicker = ({ capability, value, onChange, label, className }: ModelRegionPickerProps) => {
  const { modelName, region, fallback } = useModelRegionResolution(capability, value, onChange)
  const modelTitle = `Default ${capability} model (${value.modelId || fallback.code})`

  return (
    <div className={cn('flex items-end gap-3', className)}>
      {label && (
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider shrink-0 pb-2.5">
          {label}
        </span>
      )}
      <PickerBadge heading="Model" icon={Cpu} text={modelName} title={modelTitle} />
      <PickerBadge heading="Region" icon={Globe} text={region} title="Default Gemini / Vertex AI region" mono />
    </div>
  )
}

/** Invalidate the shared cache (e.g., after editing models) */
export const invalidateModelCache = () => {
  _modelsCache = null
  _defaultsCache = null
}


