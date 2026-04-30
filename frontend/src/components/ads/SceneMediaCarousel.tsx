import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ImageIcon, Loader2, Video } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  thumbnailUrl?: string
  videoUrl?: string
  isGeneratingFrame: boolean
  isGeneratingVideo: boolean
}

export const SceneMediaCarousel = ({
  thumbnailUrl,
  videoUrl,
  isGeneratingFrame,
  isGeneratingVideo,
}: Props) => {
  const [activeSlide, setActiveSlide] = useState<'image' | 'video'>('image')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const hasImage = !!thumbnailUrl
  const hasVideo = !!videoUrl
  const hasBoth = hasImage && hasVideo
  const isGenerating = isGeneratingFrame || isGeneratingVideo

  // Auto-cycle between image and video when both exist.
  useEffect(() => {
    if (!hasBoth || isGenerating) {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    timerRef.current = setInterval(() => {
      setActiveSlide((prev) => (prev === 'image' ? 'video' : 'image'))
    }, 5000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [hasBoth, isGenerating])

  // Show the right slide when only one media type exists.
  useEffect(() => {
    if (hasVideo && !hasImage) setActiveSlide('video')
    else setActiveSlide('image')
  }, [hasImage, hasVideo])

  if (isGeneratingFrame) return <_GeneratingPlaceholder label="Generating frame..." />
  if (isGeneratingVideo) return <_GeneratingPlaceholder label="Generating video..." />
  if (!hasImage && !hasVideo) return <_EmptyPlaceholder />

  return (
    <>
      <AnimatePresence mode="wait">
        {activeSlide === 'image' && hasImage && (
          <motion.img
            key="image"
            src={thumbnailUrl}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4 }}
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}
        {activeSlide === 'video' && hasVideo && (
          <motion.video
            key="video"
            src={videoUrl}
            controls
            playsInline
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4 }}
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}
      </AnimatePresence>

      {hasBoth && (
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5 z-10">
          <_SlideButton
            active={activeSlide === 'image'}
            icon={<ImageIcon size={8} />}
            label="IMG"
            onClick={() => setActiveSlide('image')}
          />
          <_SlideButton
            active={activeSlide === 'video'}
            icon={<Video size={8} />}
            label="VID"
            onClick={() => setActiveSlide('video')}
          />
        </div>
      )}

      {!hasBoth && hasVideo && (
        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider bg-black/40 text-white/70 backdrop-blur-md border border-white/10 z-10">
          <Video size={8} /> Video
        </div>
      )}
    </>
  )
}

const _GeneratingPlaceholder = ({ label }: { label: string }) => (
  <div className="w-full h-full bg-muted flex items-center justify-center">
    <div className="flex flex-col items-center gap-1">
      <Loader2 className="animate-spin text-accent" size={20} />
      <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-widest">
        {label}
      </span>
    </div>
  </div>
)

const _EmptyPlaceholder = () => (
  <div className="w-full h-full bg-muted flex flex-col items-center justify-center gap-2 text-muted-foreground">
    <ImageIcon size={24} strokeWidth={1.5} />
    <span className="text-[9px] font-bold uppercase tracking-widest">No media yet</span>
  </div>
)

const _SlideButton = ({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean
  icon: React.ReactNode
  label: string
  onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={cn(
      'flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider backdrop-blur-md border transition-all',
      active
        ? 'bg-white/90 text-black border-white/50'
        : 'bg-black/40 text-white/70 border-white/10 hover:bg-black/60',
    )}
  >
    {icon} {label}
  </button>
)
