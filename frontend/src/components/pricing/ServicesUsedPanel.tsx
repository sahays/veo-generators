import { useEffect, useState } from 'react'
import { Cpu, DollarSign, Loader2 } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { Card } from '@/components/Common'
import { cn } from '@/lib/utils'
import type { FeatureId, FeaturePricing, ServiceLineItem } from '@/types/project'

interface ServicesUsedPanelProps {
  feature: FeatureId
  recordId?: string
  className?: string
  title?: string
}

interface RawCatalogService {
  id: string
  label: string
  unit?: ServiceLineItem['unit']
  unit_cost_usd?: number
}

const fmt = (n: number) => (n >= 0.01 ? `$${n.toFixed(3)}` : `$${n.toFixed(4)}`)

const unitLabel = (item: ServiceLineItem) => {
  if (item.unit === 'token') return `${item.units.toLocaleString()} tokens`
  if (item.unit === 'second') return `${item.units.toFixed(0)}s`
  if (item.unit === 'minute') return `${item.units.toFixed(2)} min`
  return `${item.units}`
}

async function fetchFeaturePricing(feature: FeatureId, recordId?: string): Promise<FeaturePricing> {
  if (recordId) {
    return api.pricing.usage(feature, recordId)
  }
  const features = await api.pricing.features()
  const f = features.features?.[feature]
  if (!f) {
    return { feature, services: [], total_usd: 0 }
  }
  const rawServices: RawCatalogService[] = f.services || []
  return {
    feature,
    services: rawServices.map((s) => ({
      id: s.id,
      label: s.label,
      unit: s.unit || 'token',
      units: 0,
      unit_cost_usd: s.unit_cost_usd || 0,
      subtotal_usd: 0,
    })),
    total_usd: 0,
  }
}

const ServiceRow = ({ item, hasRecord }: { item: ServiceLineItem; hasRecord: boolean }) => (
  <div className="flex items-start justify-between gap-2 text-xs">
    <div className="min-w-0">
      <p className="text-foreground font-medium truncate">{item.label}</p>
      <p className="text-[10px] text-muted-foreground font-mono">
        {hasRecord ? unitLabel(item) : `@ ${fmt(item.unit_cost_usd)}/${item.unit}`}
      </p>
    </div>
    <span className="text-accent-dark font-mono font-semibold shrink-0">
      {hasRecord ? fmt(item.subtotal_usd) : fmt(item.unit_cost_usd)}
    </span>
  </div>
)

const PricingConfidenceFooter = ({ data }: { data: FeaturePricing }) => {
  if (!data.confidence || data.confidence === 'high') return null
  return (
    <div className="pt-2 border-t border-border/30">
      <p
        className={cn(
          'text-[9px] uppercase tracking-widest font-bold',
          data.confidence === 'medium' ? 'text-amber-500' : 'text-red-500',
        )}
      >
        {data.confidence === 'medium' ? 'Approximate' : 'Estimated'}
      </p>
      {data.notes && (
        <p className="text-[10px] text-muted-foreground mt-1 leading-snug">{data.notes}</p>
      )}
    </div>
  )
}

const PricingSummaryContent = ({ data, recordId }: { data: FeaturePricing; recordId?: string }) => (
  <div className="space-y-2.5">
    {data.services.length === 0 && (
      <p className="text-xs text-muted-foreground">No services recorded yet.</p>
    )}
    {data.services.map((item) => (
      <ServiceRow key={item.id} item={item} hasRecord={Boolean(recordId)} />
    ))}
    {recordId && (
      <div className="flex items-center justify-between pt-2.5 border-t border-border/50">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
          <DollarSign size={10} /> Total
        </span>
        <span className="text-sm font-mono font-bold text-accent-dark">{fmt(data.total_usd)}</span>
      </div>
    )}
    {recordId && <PricingConfidenceFooter data={data} />}
  </div>
)

function useFeaturePricing(feature: FeatureId, recordId?: string) {
  const [data, setData] = useState<FeaturePricing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchFeaturePricing(feature, recordId)
      .then((res) => { if (!cancelled) setData(res) })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load pricing')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [feature, recordId])

  return { data, loading, error }
}

export const ServicesUsedPanel = ({ feature, recordId, className, title = 'Services Used' }: ServicesUsedPanelProps) => {
  const { data, loading, error } = useFeaturePricing(feature, recordId)

  return (
    <Card id={`services-used-${feature}`} title={title} icon={Cpu} className={className}>
      {loading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground py-3">
          <Loader2 className="animate-spin" size={12} /> Loading pricing…
        </div>
      )}
      {error && <div className="text-xs text-red-500 py-2">{error}</div>}
      {!loading && !error && data && <PricingSummaryContent data={data} recordId={recordId} />}
    </Card>
  )
}


