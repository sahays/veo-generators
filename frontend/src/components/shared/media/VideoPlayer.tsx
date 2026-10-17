import { cn } from '@/lib/utils'

interface VideoPlayerProps {
  src: string
  maxWidth?: string
  className?: string
}

export const VideoPlayer = ({ src, maxWidth = 'max-w-lg', className }: VideoPlayerProps) => {
  return (
    <div className={cn("aspect-video bg-black rounded-xl overflow-hidden border border-border", maxWidth, className)}>
      <video src={src} controls className="w-full h-full object-contain" />
    </div>
  )
}
