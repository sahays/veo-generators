import { Link } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
} from 'lucide-react'

interface Variant {
  aspect_ratio: string
  status: string
  output_signed_url?: string
  prompt_text_used?: string
  error_message?: string
}

interface Props {
  recordId: string
  variants: Variant[]
}

export const AdaptVariantGrid = ({ recordId, variants }: Props) => {
  if (variants.length === 0) return null
  const completedCount = variants.filter((v) => v.status === 'completed').length
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
        Variants ({completedCount}/{variants.length})
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {variants.map((variant, i) => (
          <VariantCard key={i} variant={variant} index={i} recordId={recordId} />
        ))}
      </div>
    </div>
  )
}

const VariantCard = ({
  variant,
  index,
  recordId,
}: {
  variant: Variant
  index: number
  recordId: string
}) => (
  <div className="glass bg-card rounded-xl border border-border overflow-hidden">
    {variant.status === 'completed' && variant.output_signed_url ? (
      <div className="bg-muted/30 flex items-center justify-center p-3">
        <img
          src={variant.output_signed_url}
          alt={`${variant.aspect_ratio} variant`}
          className="max-w-full max-h-64 rounded-lg object-contain"
        />
      </div>
    ) : variant.status === 'failed' ? (
      <div className="aspect-video bg-red-500/5 flex items-center justify-center">
        <AlertCircle size={24} className="text-red-400" />
      </div>
    ) : (
      <div className="aspect-video bg-muted/30 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    )}
    <div className="p-3 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="text-sm font-heading font-bold text-foreground">
          {variant.aspect_ratio}
        </span>
        {variant.status === 'completed' && (
          <CheckCircle2 size={14} className="text-emerald-500" />
        )}
        {variant.status === 'failed' && <AlertCircle size={14} className="text-red-500" />}
      </div>
      <div className="flex items-center gap-1">
        {variant.status === 'completed' && variant.prompt_text_used && (
          <Link
            to={`/adapts/${recordId}/prompt/${index}`}
            target="_blank"
            className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="View prompt"
          >
            <ExternalLink size={14} />
          </Link>
        )}
        {variant.status === 'completed' && variant.output_signed_url && (
          <a
            href={variant.output_signed_url}
            download
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            title="Download"
          >
            <Download size={14} />
          </a>
        )}
      </div>
    </div>
    {variant.status === 'failed' && variant.error_message && (
      <p className="px-3 pb-3 text-[10px] text-red-500 line-clamp-2">
        {variant.error_message}
      </p>
    )}
  </div>
)
