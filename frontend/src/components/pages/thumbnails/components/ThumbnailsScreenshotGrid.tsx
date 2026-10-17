import { motion } from 'framer-motion'
import { Camera, Loader2, Tag } from 'lucide-react'
import { AnchorHeading } from '@/components/Common'
import type { ThumbnailScreenshot } from '@/types/project'

interface Props {
  screenshots: (ThumbnailScreenshot & { localUrl?: string })[]
  capturing: boolean
  captureProgress: number
}

export const ThumbnailsScreenshotGrid = ({
  screenshots,
  capturing,
  captureProgress,
}: Props) => (
  <div className="space-y-4">
    <div className="flex items-center gap-2">
      <Camera size={16} className="text-accent-dark" />
      <AnchorHeading id="screenshots" className="text-base font-heading font-bold text-foreground">
        {screenshots.length} Screenshots {capturing ? 'Capturing...' : 'Captured'}
      </AnchorHeading>
      {capturing && (
        <span className="text-xs text-muted-foreground">
          ({captureProgress}/{screenshots.length})
        </span>
      )}
    </div>

    <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {screenshots.map((screenshot, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
          className="rounded-xl border border-border bg-card overflow-hidden"
        >
          <div className="aspect-video bg-black relative">
            {screenshot.localUrl ? (
              <img
                src={screenshot.localUrl}
                alt={screenshot.title}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <Loader2 className="animate-spin text-accent" size={20} />
              </div>
            )}
            <span className="absolute top-2 left-2 text-[9px] font-mono font-bold text-white bg-black/70 px-1.5 py-0.5 rounded">
              {screenshot.timestamp}
            </span>
          </div>

          <div className="p-3 space-y-1.5">
            <p className="text-xs font-bold text-foreground line-clamp-1">
              {screenshot.title}
            </p>
            <p className="text-[10px] text-muted-foreground line-clamp-2 leading-relaxed">
              {screenshot.visual_characteristics}
            </p>
            {screenshot.tags && screenshot.tags.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                <Tag size={8} className="text-muted-foreground shrink-0" />
                {screenshot.tags.slice(0, 3).map((tag, j) => (
                  <span key={j} className="text-[8px] px-1 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  </div>
)
