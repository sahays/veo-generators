import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import type { AdaptRecord } from '@/types/project'

export const AdaptsOutputPage = () => {
  const { id, variantIndex } = useParams<{ id: string; variantIndex?: string }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<AdaptRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api.adapts.get(id)
      .then(setRecord)
      .catch((err: any) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    )
  }

  if (error || !record) {
    return (
      <div className="space-y-4 max-w-3xl mx-auto py-12 px-6">
        <button onClick={() => navigate(`/adapts/${id}`)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Adapt
        </button>
        <p className="text-sm text-red-500">{error || 'Record not found'}</p>
      </div>
    )
  }

  const title = record.display_name || record.source_filename || 'Adapt'
  const idx = variantIndex !== undefined ? parseInt(variantIndex, 10) : 0
  const variant = record.variants[idx]

  if (!variant) {
    return (
      <div className="space-y-4 max-w-3xl mx-auto py-12 px-6">
        <button onClick={() => navigate(`/adapts/${id}`)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Adapt
        </button>
        <p className="text-sm text-red-500">Variant not found</p>
      </div>
    )
  }

  const promptText = variant.prompt_text_used

  return (
    <div className="max-w-3xl mx-auto py-8 px-6 space-y-6">
      <button onClick={() => navigate(`/adapts/${id}`)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
        <ArrowLeft size={16} /> Back to Adapt
      </button>

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-heading font-bold text-foreground">
            Adapt Prompt — {variant.aspect_ratio}
          </h1>
          <ModelPill modelName={record?.usage?.model_name} />
        </div>
        <p className="text-sm text-muted-foreground">{title}</p>
      </div>

      {/* Variant navigation */}
      {record.variants.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {record.variants.map((v, i) => (
            <button
              key={i}
              onClick={() => navigate(`/adapts/${id}/prompt/${i}`, { replace: true })}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                i === idx
                  ? 'bg-accent/10 text-accent-dark border border-accent/30'
                  : 'bg-muted text-muted-foreground hover:text-foreground border border-transparent'
              }`}
            >
              {v.aspect_ratio}
            </button>
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
