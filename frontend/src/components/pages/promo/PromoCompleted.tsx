import { Download } from 'lucide-react'
import { AnchorHeading } from '@/components/Common'

interface PromoSegment {
  title: string
  timestamp_start: string
  timestamp_end: string
  description: string
  overlay_signed_url?: string
}

interface Props {
  record: {
    output_signed_url?: string
    thumbnail_signed_url?: string
    segments?: PromoSegment[]
    usage?: { cost_usd: number; input_tokens: number; output_tokens: number }
  }
}

export const PromoCompleted = ({ record }: Props) => (
  <div className="space-y-6">
    {record.output_signed_url && (
      <div className="space-y-2">
        <AnchorHeading id="promo-output" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Promo Output
        </AnchorHeading>
        <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border max-w-2xl">
          <video src={record.output_signed_url} controls className="w-full h-full object-contain" />
        </div>
      </div>
    )}

    {record.output_signed_url && (
      <div className="flex gap-3">
        <a
          href={record.output_signed_url}
          download
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-dark transition-colors"
        >
          <Download size={16} /> Download Promo
        </a>
      </div>
    )}

    {record.thumbnail_signed_url && (
      <div className="space-y-2">
        <AnchorHeading id="title-card" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Title Card
        </AnchorHeading>
        <img
          src={record.thumbnail_signed_url}
          alt="Title card collage"
          className="rounded-xl border border-border max-w-md"
        />
      </div>
    )}

    {record.segments && record.segments.length > 0 && (
      <div className="space-y-3">
        <AnchorHeading id="selected-moments" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Selected Moments
        </AnchorHeading>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {record.segments.map((seg, i) => (
            <div key={i} className="glass bg-card p-4 rounded-xl border border-border">
              {seg.overlay_signed_url && (
                <img
                  src={seg.overlay_signed_url}
                  alt={seg.title}
                  className="w-full rounded-lg mb-2 bg-black"
                />
              )}
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[10px] font-mono text-muted-foreground">
                  {seg.timestamp_start} - {seg.timestamp_end}
                </span>
              </div>
              <h4 className="text-sm font-heading font-bold text-foreground mb-1">{seg.title}</h4>
              <p className="text-xs text-muted-foreground line-clamp-2">{seg.description}</p>
            </div>
          ))}
        </div>
      </div>
    )}

    {record.usage && record.usage.cost_usd > 0 && (
      <div className="text-xs text-muted-foreground">
        AI cost: ${record.usage.cost_usd.toFixed(4)} (
        {record.usage.input_tokens + record.usage.output_tokens} tokens)
      </div>
    )}
  </div>
)
