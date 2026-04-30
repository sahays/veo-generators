import { ImageIcon, Loader2, Mic, Music, Pencil, Video } from 'lucide-react'
import { Card } from '@/components/Common'
import { SceneMediaCarousel } from '@/components/ads/SceneMediaCarousel'
import { AudioToggle, StatusIcon } from '@/components/ads/SceneItemShared'
import { cn } from '@/lib/utils'
import type { Scene } from '@/types/project'

interface Props {
  scene: Scene
  index: number
  isReadOnly: boolean
  aspectClass: string
  isGeneratingFrame: boolean
  isGeneratingVideo: boolean
  isBusy: boolean
  error: string | null
  handleToggle: (updates: Partial<Scene>) => void
  handleTextChange: (updates: Partial<Scene>) => void
  handleGenerateFrame: () => void
  handleGenerateVideo: () => void
  onShowPromptModal: () => void
}

export const SceneItemGrid = ({
  scene,
  index,
  isReadOnly,
  aspectClass,
  isGeneratingFrame,
  isGeneratingVideo,
  isBusy,
  error,
  handleToggle,
  handleTextChange,
  handleGenerateFrame,
  handleGenerateVideo,
  onShowPromptModal,
}: Props) => (
  <Card className="p-0 overflow-hidden group border-border/40 hover:border-accent/50 transition-all">
    <div className={cn('relative overflow-hidden', aspectClass)}>
      <SceneMediaCarousel
        thumbnailUrl={scene.thumbnail_url}
        videoUrl={scene.video_url}
        isGeneratingFrame={isGeneratingFrame}
        isGeneratingVideo={isGeneratingVideo}
      />
      <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity p-4 flex flex-col justify-end gap-2">
        <div className="flex flex-wrap gap-1">
          {Object.values(scene.metadata || {}).slice(0, 3).map((v, i) => (
            <span key={i} className="text-[8px] font-bold uppercase bg-white/20 backdrop-blur-md px-1.5 py-0.5 rounded text-white border border-white/10">
              {v}
            </span>
          ))}
        </div>
      </div>
      <div className="absolute top-3 left-3 bg-black/60 backdrop-blur-md px-2 py-1 rounded text-[10px] font-mono text-white border border-white/10">
        {scene.timestamp_start}
      </div>
    </div>

    <div className="p-4 space-y-3 bg-card/50">
      <textarea
        value={scene.visual_description}
        onChange={(e) => handleTextChange({ visual_description: e.target.value })}
        readOnly={isReadOnly}
        className={cn(
          'w-full text-xs leading-relaxed bg-transparent border-none focus:ring-0 outline-none resize-none p-0 min-h-[60px]',
          isReadOnly && 'cursor-default',
        )}
        placeholder="Scene description..."
      />

      <div className="flex items-center gap-3">
        <AudioToggle
          checked={!!scene.narration_enabled}
          onChange={(v) => handleToggle({ narration_enabled: v })}
          disabled={isReadOnly}
          icon={<Mic size={10} className="text-accent-dark" />}
          label="Voice"
        />
        <AudioToggle
          checked={!!scene.music_enabled}
          onChange={(v) => handleToggle({ music_enabled: v })}
          disabled={isReadOnly}
          icon={<Music size={10} className="text-accent-dark" />}
          label="Music"
        />
      </div>
      {scene.narration_enabled && scene.narration && (
        <p className="text-[10px] italic text-muted-foreground truncate" title={scene.narration}>
          {scene.narration}
        </p>
      )}
      {scene.music_enabled && scene.music_description && (
        <p className="text-[10px] text-muted-foreground truncate" title={scene.music_description}>
          {scene.music_description}
        </p>
      )}

      {error && <p className="text-[10px] text-red-500">{error}</p>}
      <div className="flex items-center justify-between pt-2 border-t border-border/50">
        <span className="text-[10px] font-bold uppercase text-muted-foreground flex items-center gap-1.5">
          Scene {index + 1}
          <StatusIcon status={scene.status} />
        </span>
        <div className="flex gap-2">
          <button
            onClick={onShowPromptModal}
            className="p-1.5 hover:bg-accent/10 rounded-md text-muted-foreground hover:text-accent-dark transition-colors"
            title="Edit Prompt"
          >
            <Pencil size={14} />
          </button>
          {!isReadOnly && (
            <>
              <button
                onClick={handleGenerateFrame}
                disabled={isBusy}
                className="p-1.5 hover:bg-accent/10 rounded-md text-accent-dark transition-colors disabled:opacity-40"
                title="Generate Frame (2 credits)"
              >
                {isGeneratingFrame ? <Loader2 size={14} className="animate-spin" /> : <ImageIcon size={14} />}
              </button>
              <button
                onClick={handleGenerateVideo}
                disabled={isBusy}
                className="p-1.5 hover:bg-accent/10 rounded-md text-accent-dark transition-colors disabled:opacity-40"
                title="Generate Video (5 credits)"
              >
                {isGeneratingVideo ? <Loader2 size={14} className="animate-spin" /> : <Video size={14} />}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  </Card>
)
