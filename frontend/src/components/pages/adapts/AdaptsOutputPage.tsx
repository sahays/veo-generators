import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/hooks/useApiClient'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import type { AdaptRecord, AdaptVariant } from '@/types/project'

const AdaptErrorFallback = ({ id, message, onBack }: { id?: string; message: string; onBack: () => void }) => (
  <div className="space-y-4 max-w-3xl mx-auto py-12 px-6" data-record-id={id}>
    <Button variant="link" icon={ArrowLeft} onClick={onBack} className="text-sm">
      Back to Adapt
    </Button>
    <p className="text-sm text-red-500">{message}</p>
  </div>
)

const AdaptOutputContent = ({
  id,
  record,
  variant,
  idx,
  onBack,
  onSelectVariant,
}: {
  id?: string
  record: AdaptRecord
  variant: AdaptVariant
  idx: number
  onBack: () => void
  onSelectVariant: (index: number) => void
}) => {
  const title = record.display_name || record.source_filename || 'Adapt'
  const promptText = variant.prompt_text_used
  return (
    <div className="max-w-3xl mx-auto py-8 px-6 space-y-6">
      <Button variant="link" icon={ArrowLeft} onClick={onBack} className="text-sm">
        Back to Adapt
      </Button>
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-heading font-bold text-foreground">
            Adapt Prompt — {variant.aspect_ratio}
          </h1>
          <ModelPill modelName={record?.usage?.model_name} />
        </div>
        <p className="text-sm text-muted-foreground">{title}</p>
      </div>
      {record.variants.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {record.variants.map((v, i) => (
            <Button
              key={i}
              variant={i === idx ? 'outline' : 'secondary'}
              size="xs"
              onClick={() => onSelectVariant(i)}
              className={i === idx ? 'bg-accent/10 text-accent-dark border-accent/30' : ''}
            >
              {v.aspect_ratio}
            </Button>
          ))}
        </div>
      )}
      <div className="border border-border rounded-xl p-6 bg-card">
        {promptText ? (
          <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
            {promptText}
          </pre>
        ) : (
          <p className="text-muted-foreground">
            No prompt data available for this variant. The adapt may still be processing or was created before prompt logging was added.
          </p>
        )}
      </div>
      {id && <ServicesUsedPanel feature="adapts" recordId={id} />}
    </div>
  )
}

export const AdaptsOutputPage = () => {
  const { id, variantIndex } = useParams<{ id: string; variantIndex?: string }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<AdaptRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api.adapts.get(id).then(setRecord).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load adapt')).finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    )
  }
  const goBack = () => navigate(`/adapts/${id}`)
  if (error || !record) return <AdaptErrorFallback id={id} message={error || 'Record not found'} onBack={goBack} />
  const idx = variantIndex !== undefined ? parseInt(variantIndex, 10) : 0
  const variant = record.variants[idx]
  if (!variant) return <AdaptErrorFallback id={id} message="Variant not found" onBack={goBack} />
  return <AdaptOutputContent id={id} record={record} variant={variant} idx={idx} onBack={goBack} onSelectVariant={(i) => navigate(`/adapts/${id}/prompt/${i}`, { replace: true })} />
}
