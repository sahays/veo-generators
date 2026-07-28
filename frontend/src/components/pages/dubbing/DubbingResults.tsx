import { Download, Languages, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'

export interface DubVariant {
  language_code: string
  status: string
  output_signed_url?: string
  srt_signed_url?: string
  translated_transcript?: string
  lag_sec?: number
  error_message?: string
}

interface DubbingResultsProps {
  variants: DubVariant[]
  languageNames: Record<string, string>
}

const STATUS_PILL: Record<string, string> = {
  completed: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20',
  failed: 'bg-red-500/10 text-red-600 border-red-500/20',
  generating: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  pending: 'bg-slate-500/10 text-slate-600 border-slate-500/20',
}

const VariantBlock = ({ variant, name }: { variant: DubVariant; name: string }) => (
  <div className="glass bg-card rounded-xl p-4 space-y-3">
    <div className="flex items-center gap-2">
      <Languages size={14} className="text-muted-foreground" />
      <h4 className="text-sm font-heading font-bold text-foreground">{name}</h4>
      <span
        className={cn(
          'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border',
          STATUS_PILL[variant.status] || STATUS_PILL.pending,
        )}
      >
        {variant.status}
      </span>
      {variant.status === 'generating' && (
        <Loader2 size={12} className="animate-spin text-blue-500" />
      )}
      {/* Surfaced because it is the number that explains a dub that feels
          out of sync — worth seeing without digging into logs. */}
      {variant.status === 'completed' && !!variant.lag_sec && (
        <span className="text-[10px] text-muted-foreground">
          {variant.lag_sec.toFixed(1)}s lag corrected
        </span>
      )}
    </div>

    {variant.status === 'failed' && variant.error_message && (
      <ErrorDisplay error={variant.error_message} size="sm" />
    )}

    {variant.output_signed_url && (
      <div className="aspect-video bg-black rounded-lg overflow-hidden border border-border">
        <video src={variant.output_signed_url} controls className="w-full h-full object-contain" />
      </div>
    )}

    {variant.translated_transcript && (
      <details className="group">
        <summary className="text-xs font-medium text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
          Translated transcript
        </summary>
        <p className="mt-2 text-xs text-foreground/80 leading-relaxed whitespace-pre-wrap">
          {variant.translated_transcript}
        </p>
      </details>
    )}

    <div className="flex items-center gap-3">
      {variant.output_signed_url && (
        <a
          href={variant.output_signed_url}
          download
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-accent-dark transition-colors"
        >
          <Download size={12} /> Video
        </a>
      )}
      {variant.srt_signed_url && (
        <a
          href={variant.srt_signed_url}
          download
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-accent-dark transition-colors"
        >
          <Download size={12} /> Subtitles (.srt)
        </a>
      )}
    </div>
  </div>
)

export const DubbingResults = ({ variants, languageNames }: DubbingResultsProps) => (
  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
    {variants.map((variant) => (
      <VariantBlock
        key={variant.language_code}
        variant={variant}
        name={languageNames[variant.language_code] || variant.language_code.toUpperCase()}
      />
    ))}
  </div>
)
