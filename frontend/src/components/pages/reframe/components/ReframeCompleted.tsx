import { Download } from 'lucide-react'
import { AnchorHeading, Button } from '@/components/Common'
import { cn } from '@/lib/utils'

interface Props {
  record: {
    source_signed_url?: string
    output_signed_url?: string
    blurred_bg?: boolean
    output_aspect_ratio?: string
    usage?: { cost_usd: number; input_tokens: number; output_tokens: number }
  }
}

const ReframeVideoComparison = ({
  sourceUrl,
  outputUrl,
  is34,
  arLabel,
}: {
  sourceUrl?: string
  outputUrl?: string
  is34: boolean
  arLabel: string
}) => (
  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
    {sourceUrl && (
      <div className="space-y-2">
        <AnchorHeading id="original-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Original (16:9)
        </AnchorHeading>
        <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border">
          <video src={sourceUrl} controls className="w-full h-full object-contain" />
        </div>
      </div>
    )}
    {outputUrl && (
      <div className="space-y-2">
        <AnchorHeading id="reframed-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Reframed ({arLabel})
        </AnchorHeading>
        <div
          className={cn(
            'bg-black rounded-xl overflow-hidden border border-border max-w-xs',
            is34 ? 'aspect-[3/4]' : 'aspect-[9/16]',
          )}
        >
          <video src={outputUrl} controls className="w-full h-full object-contain" />
        </div>
      </div>
    )}
  </div>
)

export const ReframeCompleted = ({ record }: Props) => {
  const is34 = record.output_aspect_ratio === '3:4'
  const arLabel = is34 ? '3:4' : '9:16'
  return (
    <div className="space-y-6">
      <ReframeVideoComparison sourceUrl={record.source_signed_url} outputUrl={record.output_signed_url} is34={is34} arLabel={arLabel} />
      {record.output_signed_url && (
        <div className="flex gap-3">
          <Button href={record.output_signed_url} download target="_blank" rel="noopener noreferrer" icon={Download}>
            Download {arLabel} Video
          </Button>
        </div>
      )}
      {record.usage && record.usage.cost_usd > 0 && (
        <div className="text-xs text-muted-foreground">
          AI cost: ${record.usage.cost_usd.toFixed(4)} ({record.usage.input_tokens + record.usage.output_tokens} tokens)
        </div>
      )}
    </div>
  )
}
