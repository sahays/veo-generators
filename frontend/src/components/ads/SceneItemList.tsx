import { ImageIcon, Loader2, Mic, Music, Pencil, Video } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { SceneMediaCarousel } from '@/components/ads/SceneMediaCarousel'
import { AudioToggle, StatusBadge } from '@/components/ads/SceneItemShared'
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

export const SceneItemList = ({
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
  <Card className="p-4 overflow-hidden group transition-all duration-300">
    <div className="flex items-center gap-2 mb-3">
      <span className="text-base font-heading font-bold text-foreground">
        Scene {index + 1}: {scene.timestamp_start} - {scene.timestamp_end}
      </span>
      <StatusBadge status={scene.status} />
    </div>
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      <div className="space-y-4 lg:col-span-8">
        <textarea
          value={scene.visual_description}
          onChange={(e) => handleTextChange({ visual_description: e.target.value })}
          readOnly={isReadOnly}
          className={cn(
            'w-full min-h-[100px] p-3 rounded-xl text-sm leading-relaxed bg-muted/30 border border-border focus:ring-2 focus:ring-accent/30 outline-none resize-none transition-all',
            isReadOnly && 'cursor-default bg-transparent',
          )}
          placeholder="Scene visual description..."
        />

        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-4">
            <AudioToggle
              checked={!!scene.narration_enabled}
              onChange={(v) => handleToggle({ narration_enabled: v })}
              disabled={isReadOnly}
              icon={<Mic size={12} className="text-accent-dark" />}
              label="Voice-Over"
            />
            <AudioToggle
              checked={!!scene.music_enabled}
              onChange={(v) => handleToggle({ music_enabled: v })}
              disabled={isReadOnly}
              icon={<Music size={12} className="text-accent-dark" />}
              label="Music"
            />
          </div>
          {scene.narration_enabled && (
            <textarea
              value={scene.narration || ''}
              onChange={(e) => handleTextChange({ narration: e.target.value })}
              readOnly={isReadOnly}
              className={cn(
                'w-full min-h-[60px] p-3 rounded-xl text-sm leading-relaxed italic bg-muted/20 border border-border/50 focus:ring-2 focus:ring-accent/30 outline-none resize-none transition-all',
                isReadOnly && 'cursor-default bg-transparent',
              )}
              placeholder="Voice-over narration text..."
            />
          )}
          {scene.music_enabled && (
            <input
              type="text"
              value={scene.music_description || ''}
              onChange={(e) => handleTextChange({ music_description: e.target.value })}
              readOnly={isReadOnly}
              className={cn(
                'w-full p-2.5 rounded-xl text-sm bg-muted/20 border border-border/50 focus:ring-2 focus:ring-accent/30 outline-none transition-all',
                isReadOnly && 'cursor-default bg-transparent',
              )}
              placeholder="Background music: genre, tempo, instruments, mood..."
            />
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {Object.entries(scene.metadata || {}).map(([key, value]) => (
            <div key={key} className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-accent/10 border border-accent/20 text-[9px] font-bold uppercase tracking-wider text-accent-dark">
              <span className="opacity-60">{key}:</span>
              <span>{value}</span>
            </div>
          ))}
        </div>

        {error && <p className="text-[10px] text-red-500">{error}</p>}

        <div className="flex items-center gap-3">
          {!isReadOnly && (
            <>
              <Button
                variant="secondary"
                className="h-7 px-2.5 text-[10px]"
                icon={isGeneratingFrame ? Loader2 : ImageIcon}
                onClick={handleGenerateFrame}
                disabled={isBusy}
              >
                {isGeneratingFrame ? 'Generating...' : 'Generate Frame (2)'}
              </Button>
              <Button
                variant="ghost"
                className="h-7 px-2.5 text-[10px]"
                icon={isGeneratingVideo ? Loader2 : Video}
                onClick={handleGenerateVideo}
                disabled={isBusy}
              >
                {isGeneratingVideo ? 'Generating...' : 'Generate Video (5)'}
              </Button>
            </>
          )}
          <button
            onClick={onShowPromptModal}
            className="h-7 px-2 flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground hover:text-accent-dark hover:bg-accent/10 rounded-md transition-colors"
            title="Edit Prompt"
          >
            <Pencil size={12} /> Edit Prompt
          </button>
        </div>
      </div>

      <div className={cn(
        'relative lg:col-span-4 rounded-xl bg-muted/50 border border-dashed border-border flex items-center justify-center overflow-hidden',
        aspectClass,
      )}>
        <SceneMediaCarousel
          thumbnailUrl={scene.thumbnail_url}
          videoUrl={scene.video_url}
          isGeneratingFrame={isGeneratingFrame}
          isGeneratingVideo={isGeneratingVideo}
        />
      </div>
    </div>
  </Card>
)
