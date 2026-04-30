import { Download } from 'lucide-react'
import { AnchorHeading } from '@/components/Common'
import { cn } from '@/lib/utils'

interface Props {
  record: {
    source_signed_url?: string
    output_signed_url?: string
    blurred_bg?: boolean
    usage?: { cost_usd: number; input_tokens: number; output_tokens: number }
  }
}

export const ReframeCompleted = ({ record }: Props) => (
  <div className="space-y-6">
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
      {record.source_signed_url && (
        <div className="space-y-2">
          <AnchorHeading id="original-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Original (16:9)
          </AnchorHeading>
          <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border">
            <video src={record.source_signed_url} controls className="w-full h-full object-contain" />
          </div>
        </div>
      )}
      {record.output_signed_url && (
        <div className="space-y-2">
          <AnchorHeading id="reframed-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Reframed ({record.blurred_bg ? '4:5' : '9:16'})
          </AnchorHeading>
          <div
            className={cn(
              'bg-black rounded-xl overflow-hidden border border-border',
              record.blurred_bg ? 'aspect-[4/5] max-w-sm' : 'aspect-[9/16] max-w-xs',
            )}
          >
            <video src={record.output_signed_url} controls className="w-full h-full object-contain" />
          </div>
        </div>
      )}
    </div>

    {record.output_signed_url && (
      <div className="flex gap-3">
        <a
          href={record.output_signed_url}
          download
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-dark transition-colors"
        >
          <Download size={16} /> Download {record.blurred_bg ? '4:5' : '9:16'} Video
        </a>
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
