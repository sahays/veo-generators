import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ImageIcon, Loader2, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type SlideType = 'start' | 'end' | 'video'

interface Props {
  thumbnailUrl?: string
  endFrameUrl?: string
  videoUrl?: string
  isGeneratingFrame: boolean
  isGeneratingVideo: boolean
}

interface SlideItem {
  id: SlideType
  label: string
  badge: string
  icon: React.ReactNode
}

const CarouselViewport = ({
  activeSlide,
  hasStart,
  hasEnd,
  hasVideo,
  thumbnailUrl,
  endFrameUrl,
  videoUrl,
  slides,
  onPin,
  onSelectSlide,
}: {
  activeSlide: SlideType
  hasStart: boolean
  hasEnd: boolean
  hasVideo: boolean
  thumbnailUrl?: string
  endFrameUrl?: string
  videoUrl?: string
  slides: SlideItem[]
  onPin: () => void
  onSelectSlide: (id: SlideType) => void
}) => (
  <>
    <AnimatePresence mode="wait">
      {((activeSlide === 'start' && hasStart) || (activeSlide === 'end' && hasEnd)) && (
        <motion.img
          key={activeSlide}
          src={activeSlide === 'start' ? thumbnailUrl : endFrameUrl}
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
          onPlay={onPin}
          onClick={onPin}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
          className="absolute inset-0 w-full h-full object-cover"
        />
      )}
    </AnimatePresence>

    {slides.length >= 2 && (
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5 z-10">
        {slides.map((s) => (
          <_SlideButton
            key={s.id}
            active={activeSlide === s.id}
            icon={s.icon}
            label={s.label}
            onClick={() => onSelectSlide(s.id)}
          />
        ))}
      </div>
    )}

    {slides.length === 1 && (
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider bg-black/40 text-white/70 backdrop-blur-md border border-white/10 z-10">
        {slides[0].icon} {slides[0].badge}
      </div>
    )}
  </>
)

function useCarouselAutoAdvance(slideIdsKey: string, isGenerating: boolean) {
  const [activeSlide, setActiveSlide] = useState<SlideType>('start')
  const [pinned, setPinned] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const ids = slideIdsKey ? (slideIdsKey.split(',') as SlideType[]) : []
    if (ids.length < 2 || isGenerating || pinned) {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    timerRef.current = setInterval(() => {
      setActiveSlide((prev) => ids[(ids.indexOf(prev) + 1) % ids.length])
    }, 5000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [slideIdsKey, isGenerating, pinned])

  useEffect(() => {
    const ids = slideIdsKey ? (slideIdsKey.split(',') as SlideType[]) : []
    if (ids.length > 0 && !ids.includes(activeSlide)) setActiveSlide(ids[0])
  }, [slideIdsKey, activeSlide, pinned])

  return { activeSlide, setActiveSlide, setPinned }
}

export const SceneMediaCarousel = ({
  thumbnailUrl,
  endFrameUrl,
  videoUrl,
  isGeneratingFrame,
  isGeneratingVideo,
}: Props) => {
  const slides: SlideItem[] = [
    ...(thumbnailUrl ? [{ id: 'start' as const, label: 'START', badge: 'Start Frame', icon: <ImageIcon size={8} /> }] : []),
    ...(endFrameUrl ? [{ id: 'end' as const, label: 'END', badge: 'End Frame', icon: <ImageIcon size={8} /> }] : []),
    ...(videoUrl ? [{ id: 'video' as const, label: 'VID', badge: 'Video', icon: <Video size={8} /> }] : []),
  ]
  const { activeSlide, setActiveSlide, setPinned } = useCarouselAutoAdvance(
    slides.map((s) => s.id).join(','),
    isGeneratingFrame || isGeneratingVideo,
  )

  if (isGeneratingFrame) return <_GeneratingPlaceholder label="Generating frames..." />
  if (isGeneratingVideo) return <_GeneratingPlaceholder label="Generating video..." />
  if (slides.length === 0) return <_EmptyPlaceholder />

  return (
    <CarouselViewport
      activeSlide={activeSlide}
      hasStart={!!thumbnailUrl}
      hasEnd={!!endFrameUrl}
      hasVideo={!!videoUrl}
      thumbnailUrl={thumbnailUrl}
      endFrameUrl={endFrameUrl}
      videoUrl={videoUrl}
      slides={slides}
      onPin={() => setPinned(true)}
      onSelectSlide={(slide) => {
        setPinned(true)
        setActiveSlide(slide)
      }}
    />
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
  <Button
    variant="unstyled"
    onClick={onClick}
    className={cn(
      'flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[8px] font-bold uppercase tracking-wider backdrop-blur-md border transition-all',
      active
        ? 'bg-white/90 text-black border-white/50'
        : 'bg-black/40 text-white/70 border-white/10 hover:bg-black/60',
    )}
  >
    {icon} {label}
  </Button>
)
