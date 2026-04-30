import { useEffect, useRef } from 'react'
import { Loader2, User } from 'lucide-react'

interface AvatarPlayerProps {
  portraitUrl: string
  videoUrl: string | null
  isGenerating: boolean
  onPlaybackEnded?: () => void
}

export const AvatarPlayer = ({
  portraitUrl,
  videoUrl,
  isGenerating,
  onPlaybackEnded,
}: AvatarPlayerProps) => {
  const videoRef = useRef<HTMLVideoElement>(null)

  // Autoplay when a new video lands
  useEffect(() => {
    if (videoUrl && videoRef.current) {
      videoRef.current.play().catch(() => {
        /* ignored — user-gesture required */
      })
    }
  }, [videoUrl])

  return (
    <div className="relative aspect-[3/4] max-w-sm mx-auto rounded-2xl overflow-hidden bg-black border border-border shadow-2xl">
      {videoUrl ? (
        <video
          ref={videoRef}
          src={videoUrl}
          autoPlay
          playsInline
          controls
          onEnded={onPlaybackEnded}
          className="w-full h-full object-cover"
        />
      ) : portraitUrl ? (
        <img
          src={portraitUrl}
          alt="Avatar portrait"
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-muted-foreground">
          <User size={48} />
        </div>
      )}

      {isGenerating && !videoUrl && (
        <div className="absolute top-3 right-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium bg-black/60 text-white backdrop-blur-md border border-white/10">
          <Loader2 size={12} className="animate-spin" />
          Generating reply…
        </div>
      )}
    </div>
  )
}
