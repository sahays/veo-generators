import { useState, useEffect } from 'react'
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

// Shared cache so multiple pickers don't re-fetch
let _modelsCache: AIModel[] | null = null
let _regionsCache: string[] | null = null
let _defaultsCache: Record<string, any> | null = null

export const ModelRegionPicker = ({ capability, value, onChange, label, className }: ModelRegionPickerProps) => {
  const [models, setModels] = useState<AIModel[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        if (!_modelsCache || !_regionsCache || !_defaultsCache) {
          const [m, r, d] = await Promise.all([
            api.models.list(),
            api.models.regions(),
            api.models.defaults(),
          ])
          _modelsCache = m
          _regionsCache = r
          _defaultsCache = d
        }
        setModels(_modelsCache!.filter(m => m.capability === capability && m.is_active))
        setRegions(_regionsCache!)

        // Pre-select defaults if no value set
        if (!value.modelId && _defaultsCache![capability]) {
          onChange({
            modelId: _defaultsCache![capability].code,
            region: value.region || 'global',
          })
        }
      } catch (e) {
        console.error('Failed to load models:', e)
      } finally {
        setLoaded(true)
      }
    }
    load()
  }, [capability]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!loaded || models.length === 0) return null

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {label && (
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider shrink-0">
          {label}
        </span>
      )}
      <select
        value={value.modelId || ''}
        onChange={e => onChange({ ...value, modelId: e.target.value })}
        className="px-2 py-1 rounded-md bg-muted border border-border text-xs focus:outline-none focus:ring-1 focus:ring-accent min-w-0"
      >
        {models.map(m => (
          <option key={m.id} value={m.code}>
            {m.name}{m.is_default ? ' *' : ''}
          </option>
        ))}
      </select>
      <select
        value={value.region || 'global'}
        onChange={e => onChange({ ...value, region: e.target.value })}
        className="px-2 py-1 rounded-md bg-muted border border-border text-xs focus:outline-none focus:ring-1 focus:ring-accent min-w-0"
      >
        {regions.map(r => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
    </div>
  )
}

/** Invalidate the shared cache (e.g., after editing models) */
export const invalidateModelCache = () => {
  _modelsCache = null
  _regionsCache = null
  _defaultsCache = null
}
