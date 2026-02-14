import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { StoryboardFrame } from '@/types/project'

interface StoryboardViewProps {
  frames: StoryboardFrame[]
  isGenerating: boolean
}

const SkeletonFrame = ({ index }: { index: number }) => (
  <motion.div
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    transition={{ delay: index * 0.08 }}
    className="aspect-video rounded-lg overflow-hidden bg-muted"
  >
    <div className="w-full h-full animate-pulse bg-gradient-to-br from-muted via-border to-muted" />
    <div className="px-2 py-1.5 space-y-1.5">
      <div className="h-2.5 w-3/4 rounded bg-muted animate-pulse" />
      <div className="h-2 w-1/4 rounded bg-muted animate-pulse" />
    </div>
  </motion.div>
)

export const StoryboardView = ({ frames, isGenerating }: StoryboardViewProps) => {
  if (isGenerating) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-accent animate-pulse" />
          <p className="text-xs text-muted-foreground font-medium">Generating storyboard...</p>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonFrame key={i} index={i} />
          ))}
        </div>
      </div>
    )
  }

  if (frames.length === 0) return null

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground font-medium">
        Storyboard — {frames.length} frames
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {frames.map((frame, i) => (
          <motion.div
            key={frame.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
            className={cn(
              "rounded-lg overflow-hidden bg-muted border border-border",
              "hover:border-accent/40 transition-colors group"
            )}
          >
            <div className="aspect-video relative overflow-hidden">
              <img
                src={frame.imageUrl}
                alt={frame.caption}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                loading="lazy"
              />
              <div className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/70 text-white text-[10px] font-mono">
                {frame.timestamp}
              </div>
            </div>
            <div className="px-2.5 py-2">
              <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
                {frame.caption}
              </p>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
