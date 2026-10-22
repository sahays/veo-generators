import type { ReactNode } from 'react'
import { ShieldCheck, RefreshCw, Loader2, Play, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import type {
  RenderQuality,
  StoryGraphAsset,
  StoryGraphGenerationRun,
  VideoResolution,
} from '@/types/project'
import type { SelectedInspectorItem } from './storyGraphStudioTypes'

export const StepVideoRendersSection = ({
  shotsCount,
  generationRunsCount,
  activeGenerationRuns,
  assetsById,
  finalVideoUrl,
  renderQuality = 'draft',
  videoResolution = '360p',
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
  selectedItem,
  onSelectItem,
  assemblyPanel,
  keyframesPanel,
}: {
  shotsCount: number
  generationRunsCount: number
  activeGenerationRuns: StoryGraphGenerationRun[]
  assetsById: Record<string, StoryGraphAsset>
  finalVideoUrl?: string
  renderQuality?: RenderQuality
  videoResolution?: VideoResolution
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string, quality?: 'draft' | 'final') => void
  selectedItem: SelectedInspectorItem | null
  onSelectItem: (item: SelectedInspectorItem) => void
  /** Optional S10 readiness panel (blocking shots / approved-only stitch). */
  assemblyPanel?: ReactNode
  /** Optional S8_KEYFRAMES per-shot keyframe strips (shown above the render cards). */
  keyframesPanel?: ReactNode
}) => {
  const isFinal720p = renderQuality === 'final' || videoResolution === '720p'
  return (
  <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              'px-2 py-0.5 rounded text-[11px] font-mono font-bold uppercase',
              isFinal720p
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
            )}
          >
            {isFinal720p ? '720p Final' : '360p Draft'}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Drafts render at fast 360p with Gemini Omni; click &quot;Render 720p Final&quot; when ready to master in high definition.
        </p>
      </div>
      {canWrite && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant={generationRunsCount === 0 && !isFinal720p ? 'primary' : 'outline'}
            size="xs"
            icon={busyAction === 'S8_RENDER' ? Loader2 : RefreshCw}
            disabled={busyAction !== null || isRunningPipeline || shotsCount === 0}
            onClick={() => onRunStage('S8_RENDER', 'draft')}
          >
            {generationRunsCount > 0 ? 'Re-Render 360p Draft (S8)' : 'Render 360p Draft (S8)'}
          </Button>
          <Button
            variant={generationRunsCount > 0 || isFinal720p ? 'primary' : 'outline'}
            size="xs"
            icon={busyAction === 'S8_RENDER' ? Loader2 : Sparkles}
            disabled={busyAction !== null || isRunningPipeline || shotsCount === 0}
            onClick={() => onRunStage('S8_RENDER', 'final')}
          >
            {isFinal720p && generationRunsCount > 0 ? 'Re-Render 720p Final (S8)' : 'Render 720p Final (S8)'}
          </Button>
          <Button variant="outline" size="xs" icon={busyAction === 'S9_QA' ? Loader2 : ShieldCheck} disabled={busyAction !== null || isRunningPipeline || generationRunsCount === 0} onClick={() => onRunStage('S9_QA')}>
            Run Clip QA (S9)
          </Button>
          <Button variant="outline" size="xs" icon={busyAction === 'S10_ASSEMBLE' ? Loader2 : Play} disabled={busyAction !== null || isRunningPipeline || generationRunsCount === 0} onClick={() => onRunStage('S10_ASSEMBLE')}>
            Stitch Final Cut (S10)
          </Button>
        </div>
      )}
    </div>

    {keyframesPanel}

    {assemblyPanel}

    {finalVideoUrl ? (
      <Card title="Final Stitched Master Cut (S10_ASSEMBLE)" icon={Play}>
        <div className="aspect-video max-w-4xl mx-auto rounded-xl overflow-hidden bg-black border border-border">
          <video key={finalVideoUrl} controls preload="metadata" src={finalVideoUrl} className="w-full h-full" />
        </div>
      </Card>
    ) : (
      <div className="glass rounded-xl p-6 border border-dashed border-border text-center space-y-3">
        <Play size={28} className="mx-auto text-muted-foreground" />
        <div className="space-y-1">
          <p className="text-sm font-semibold text-foreground">Master Final Cut Not Yet Assembled</p>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            Click &quot;Auto Mode&quot; in the top bar or run S8_RENDER and S10_ASSEMBLE to stitch all clips into the master output.
          </p>
        </div>
      </div>
    )}

    {activeGenerationRuns.length > 0 && (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {activeGenerationRuns.map((run: StoryGraphGenerationRun) => {
          const startAsset = run.first_frame_asset_id ? assetsById[run.first_frame_asset_id] : null
          const refAssets = (run.reference_asset_ids || []).map((aid) => assetsById[aid]).filter((asset): asset is StoryGraphAsset => Boolean(asset))
          const endAsset = run.extracted_last_frame_asset_id ? assetsById[run.extracted_last_frame_asset_id] : null
          const isSelected = selectedItem?.kind === 'video_run' && selectedItem?.id === run.id
          return (
            <div
              key={run.id}
              onClick={() => onSelectItem({ kind: 'video_run', id: run.id, data: { run, startAsset, refAssets, endAsset } })}
              className={cn(
                'cursor-pointer rounded-2xl p-5 border transition-all space-y-3.5',
                isSelected ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg' : 'bg-card/80 border-border/70 hover:border-accent/50',
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <span className="text-xs font-mono font-bold text-foreground">{run.shot_id} · Attempt #{run.attempt}</span>
                  <span className="text-[10px] font-mono text-muted-foreground ml-2">({run.model || run.provider})</span>
                </div>
                <span className={cn('px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase', run.status === 'approved' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400')}>
                  {run.status}
                </span>
              </div>
              {run.output_video_signed_url && (
                <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border/60" onClick={(e) => e.stopPropagation()}>
                  <video key={run.output_video_signed_url} controls preload="metadata" src={run.output_video_signed_url} className="w-full h-full" />
                </div>
              )}
              <div className="flex items-center justify-between text-[11px] font-mono text-muted-foreground pt-1">
                <span>
                  {startAsset ? 'Start Frame + ' : ''}{refAssets.length} Refs{endAsset ? ' → End Frame Extracted' : ''}
                </span>
                <span className="text-accent-dark font-bold">Inspect Conditioning & QA →</span>
              </div>
            </div>
          )
        })}
      </div>
    )}
  </div>
  )
}
