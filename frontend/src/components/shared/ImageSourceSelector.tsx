import { Loader2, ImageIcon, ChevronRight } from 'lucide-react'
import { cn, getTimeAgo, formatFileSize } from '@/lib/utils'

export interface ImageUploadItem {
  id: string
  filename: string
  display_name?: string
  gcs_uri: string
  mime_type: string
  image_signed_url: string
  file_size_bytes: number
  createdAt: string
}

interface ImageSourceSelectorProps {
  images: ImageUploadItem[]
  loading: boolean
  selectedUri: string | null
  onSelect: (image: ImageUploadItem) => void
  emptyMessage?: string
}

export function ImageSourceSelector({
  images,
  loading,
  selectedUri,
  onSelect,
  emptyMessage = 'No uploaded images found. Upload an image in the Files section first.',
}: ImageSourceSelectorProps): JSX.Element {
  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="animate-spin text-accent" size={24} />
      </div>
    )
  }

  if (images.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">{emptyMessage}</p>
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {images.map((img) => (
        <button
          key={img.id}
          onClick={() => onSelect(img)}
          className={cn(
            "flex flex-col rounded-lg border transition-all text-left cursor-pointer overflow-hidden",
            selectedUri === img.gcs_uri
              ? "border-accent bg-accent/5 ring-1 ring-accent/30"
              : "border-border hover:border-accent/40 bg-card"
          )}
        >
          <div className="aspect-square bg-muted/50 overflow-hidden">
            <img
              src={img.image_signed_url}
              alt={img.display_name || img.filename}
              className="w-full h-full object-cover"
            />
          </div>
          <div className="p-2 min-w-0">
            <p className="text-xs font-medium text-foreground truncate">
              {img.display_name || img.filename}
            </p>
            <p className="text-[10px] text-muted-foreground">
              {formatFileSize(img.file_size_bytes)} &middot; {getTimeAgo(img.createdAt)}
            </p>
          </div>
        </button>
      ))}
    </div>
  )
}
