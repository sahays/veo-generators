import { Download, Image } from 'lucide-react'
import { AnchorHeading, Button } from '@/components/Common'

export const ThumbnailsResult = ({ thumbnailUrl }: { thumbnailUrl: string }) => (
  <div className="space-y-4">
    <div className="flex items-center gap-2">
      <Image size={16} className="text-accent-dark" />
      <AnchorHeading
        id="generated-thumbnail"
        className="text-base font-heading font-bold text-foreground"
      >
        Generated Thumbnail
      </AnchorHeading>
    </div>

    <div
      className="rounded-2xl overflow-hidden border border-border shadow-2xl"
      style={{ aspectRatio: '16/9' }}
    >
      <img
        src={thumbnailUrl}
        alt="Generated thumbnail"
        className="w-full h-full object-cover"
      />
    </div>

    <div className="flex justify-end">
      <Button
        href={thumbnailUrl}
        download="thumbnail.png"
        icon={Download}
      >
        Download Thumbnail
      </Button>
    </div>
  </div>
)
