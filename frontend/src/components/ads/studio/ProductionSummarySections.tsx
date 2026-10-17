import {
  ArrowLeft,
  Play,
  FileText,
  LayoutGrid,
  Cpu,
  CheckCircle2,
  Plus,
  Loader2,
  Eye,
  ChevronDown,
  Sparkles,
  ShieldCheck,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card, AnchorHeading } from '@/components/Common'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { CostBreakdownPill } from '@/components/ads/CostBreakdownPill'
import {
  EvalStatusPill,
  RenderQualityBadge,
  StepStatusIcon,
  StepUsageBadges,
} from './SceneItemShared'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { ModelPill } from '@/components/ModelPill'
import type { Project, Scene } from '@/types/project'

export const ProductionSummaryHeader = ({
  project,
  canWrite,
  isUpgrading,
  modelConfig,
  onModelConfigChange,
  onUpgradeToFinal,
  onOpenStudio,
  onStartFresh,
  onBack,
}: {
  project: Project
  canWrite: boolean
  isUpgrading: boolean
  modelConfig: { modelId?: string; region?: string }
  onModelConfigChange: (val: { modelId?: string; region?: string }) => void
  onUpgradeToFinal: () => void
  onOpenStudio: () => void
  onStartFresh: () => void
  onBack: () => void
}) => (
  <div className="flex flex-wrap items-center justify-between gap-4">
    <div className="flex items-center gap-4">
      <Button variant="ghost" size="icon" onClick={onBack}>
        <ArrowLeft size={20} />
      </Button>
      <div>
        <h2 className="text-2xl font-heading text-foreground tracking-tight">{project.name}</h2>
        <div className="flex flex-wrap items-center gap-2 mt-1">
          <span className="px-1.5 py-0.5 rounded bg-green-500/10 text-green-500 text-[9px] font-bold uppercase tracking-wider border border-green-500/20 flex items-center gap-1">
            <CheckCircle2 size={10} /> Published
          </span>
          <RenderQualityBadge
            quality={project.render_quality}
            resolution={project.video_resolution}
          />
          {project.eval_report && (
            <span
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-mono font-bold border inline-flex items-center gap-1',
                project.eval_report.passed
                  ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/25'
                  : 'bg-amber-500/10 text-amber-500 border-amber-500/25',
              )}
            >
              <ShieldCheck size={11} />
              AI Eval: {project.eval_report.overall_score}/100
            </span>
          )}
          <p className="text-xs text-muted-foreground">
            Generated on {new Date().toLocaleDateString()}
          </p>
        </div>
      </div>
    </div>
    <div className="flex flex-wrap items-end gap-3">
      <ModelRegionPicker capability="text" value={modelConfig} onChange={onModelConfigChange} />
      {canWrite && project.render_quality === 'draft' && (
        <Button
          variant="primary"
          icon={isUpgrading ? Loader2 : Sparkles}
          onClick={onUpgradeToFinal}
          disabled={isUpgrading}
        >
          {isUpgrading ? 'Upgrading...' : 'Upgrade to Final (720p HD)'}
        </Button>
      )}
      <Button variant="primary" icon={FileText} onClick={onOpenStudio}>
        Open StoryGraph Studio
      </Button>
      {canWrite && (
        <Button variant="outline" icon={Plus} onClick={onStartFresh}>
          New Production
        </Button>
      )}
    </div>
  </div>
)

export const ProductionVideoAndBrief = ({
  project,
  scenes,
  showAnalysisPrompt,
  onToggleAnalysisPrompt,
}: {
  project: Project
  scenes: Scene[]
  showAnalysisPrompt: boolean
  onToggleAnalysisPrompt: () => void
}) => {
  const isPortrait = project.orientation === '9:16'
  const videoSrc = project.final_video_url || project.draft_video_url
  const pipelineSteps = project.pipeline_steps || []
  const evalReport = project.eval_report

  return (
    <div className="lg:col-span-2 space-y-6">
      {videoSrc ? (
        <div
          className={cn(
            'bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5',
            isPortrait ? 'aspect-[9/16] max-w-sm mx-auto' : 'aspect-video',
          )}
        >
          <video controls className="w-full h-full" src={videoSrc} poster={scenes[0]?.thumbnail_url} />
        </div>
      ) : (
        <div
          className={cn(
            'bg-black rounded-2xl overflow-hidden shadow-2xl relative group border border-white/5',
            isPortrait ? 'aspect-[9/16] max-w-sm mx-auto' : 'aspect-video',
          )}
        >
          <div className="absolute inset-0 flex items-center justify-center bg-accent/5">
            <div className="w-20 h-20 rounded-full bg-accent/20 backdrop-blur-md flex items-center justify-center border border-accent/30">
              <Play className="text-accent-dark fill-accent-dark ml-1" size={32} />
            </div>
          </div>
          <div className="absolute bottom-6 left-6 right-6 text-center">
            <span className="text-xs text-white/60">Video not yet available</span>
          </div>
        </div>
      )}

      <Card id="production-brief" title="Production Brief" icon={FileText}>
        <p className="text-sm leading-relaxed italic">"{project.base_concept}"</p>
        <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-border/50">
          <div>
            <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Format</p>
            <p className="text-sm font-medium">{project.orientation} {project.type}</p>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Duration</p>
            <p className="text-sm font-medium">{project.video_length} seconds</p>
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Total Scenes</p>
            <p className="text-sm font-medium">{scenes.length} segments</p>
          </div>
        </div>
        {project.analysis_prompt && (
          <div className="mt-6 pt-6 border-t border-border/50">
            <Button
              variant="unstyled"
              onClick={onToggleAnalysisPrompt}
              className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronDown size={14} className={`transition-transform ${showAnalysisPrompt ? 'rotate-180' : ''}`} />
              Analysis Prompt
            </Button>
            {showAnalysisPrompt && (
              <pre className="mt-3 text-xs leading-relaxed text-foreground bg-muted/30 rounded-xl p-4 whitespace-pre-wrap break-words max-h-48 overflow-y-auto border border-border">
                {project.analysis_prompt}
              </pre>
            )}
          </div>
        )}
      </Card>

      {(pipelineSteps.length > 0 || evalReport) && (
        <Card id="pipeline-telemetry" title="Pipeline Steps & Quality Evaluation" icon={Sparkles}>
          <div className="space-y-4">
            {evalReport && (
              <div className="rounded-xl bg-muted/40 border border-border/60 p-3 space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                    <ShieldCheck size={14} className="text-emerald-500" />
                    Finished-Video AI Evaluation
                  </span>
                  <span
                    className={cn(
                      'px-2 py-0.5 rounded text-[10px] font-mono font-bold border',
                      evalReport.passed
                        ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-500 border-amber-500/20',
                    )}
                  >
                    Score: {evalReport.overall_score}/100 ({evalReport.passed ? 'Passed' : 'Needs Review'})
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{evalReport.summary}</p>
                <StepUsageBadges usage={evalReport.usage} />
              </div>
            )}

            {pipelineSteps.length > 0 && (
              <div className="divide-y divide-border/40">
                {pipelineSteps.map((step) => (
                  <div
                    key={step.step_id}
                    className="py-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                  >
                    <div className="flex items-center gap-2">
                      <StepStatusIcon status={step.status} />
                      <div>
                        <span className="text-xs font-semibold text-foreground">{step.label}</span>
                        {step.detail && (
                          <p className="text-[10px] text-muted-foreground">{step.detail}</p>
                        )}
                      </div>
                    </div>
                    <StepUsageBadges usage={step.usage} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

export const ProductionMetricsSidebar = ({
  id,
  project,
  scenesCount,
}: {
  id?: string
  project: Project
  scenesCount: number
}) => (
  <div className="space-y-6">
    <ServicesUsedPanel feature="production" recordId={id} />
    <Card id="resource-usage" title="Resource Usage" icon={Cpu}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Input Tokens</span>
          <span className="text-sm font-mono font-bold">{(project.total_usage?.input_tokens || 0).toLocaleString()}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Output Tokens</span>
          <span className="text-sm font-mono font-bold">{(project.total_usage?.output_tokens || 0).toLocaleString()}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Scenes</span>
          <span className="text-sm font-mono font-bold">{scenesCount}</span>
        </div>
        <div className="pt-3 border-t border-border/50">
          <CostBreakdownPill
            inputTokens={project.total_usage?.input_tokens || 0}
            outputTokens={project.total_usage?.output_tokens || 0}
            totalCost={project.total_usage?.cost_usd || 0}
            imageGenerations={project.total_usage?.image_generations || 0}
            imageCost={project.total_usage?.image_cost_usd || 0}
            veoVideos={project.total_usage?.veo_videos || 0}
            veoSeconds={project.total_usage?.veo_seconds || 0}
            veoUnitCost={project.total_usage?.veo_unit_cost || 0}
            veoCost={project.total_usage?.veo_cost_usd || 0}
          />
        </div>
      </div>
    </Card>

    <Card id="technical-specs" title="Technical Specs" icon={LayoutGrid}>
      <div className="space-y-3">
        <div className="flex justify-between items-center text-xs">
          <span className="text-muted-foreground">Quality Tier</span>
          <RenderQualityBadge
            quality={project.render_quality}
            resolution={project.video_resolution}
          />
        </div>
        <div className="flex justify-between items-center text-xs">
          <span className="text-muted-foreground">Orientation</span>
          <span className="font-medium">{project.orientation || '16:9'}</span>
        </div>
        <div className="flex justify-between items-center text-xs">
          <span className="text-muted-foreground">Duration</span>
          <span className="font-medium">{project.video_length}s</span>
        </div>
        <div className="flex justify-between items-center text-xs">
          <span className="text-muted-foreground">AI Model</span>
          <ModelPill modelName={project.total_usage?.model_name} />
        </div>
      </div>
    </Card>
  </div>
)

export const FinalStoryboardGrid = ({
  scenes,
  aspectClass,
  onSelectScene,
}: {
  scenes: Scene[]
  aspectClass: string
  onSelectScene: (scene: Scene) => void
}) => (
  <div className="space-y-4">
    <div className="flex items-center gap-2">
      <LayoutGrid size={18} className="text-accent-dark" />
      <AnchorHeading id="final-storyboard" className="text-lg font-heading font-bold">
        Final Storyboard
      </AnchorHeading>
    </div>
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
      {scenes.map((scene: Scene, i: number) => (
        <div key={scene.id} className="glass rounded-xl overflow-hidden group border border-border/40">
          <div className={cn('relative', aspectClass)}>
            {scene.thumbnail_url ? (
              <img src={scene.thumbnail_url} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-muted flex items-center justify-center">
                <LayoutGrid size={16} className="text-muted-foreground/30" />
              </div>
            )}
            <div className="absolute top-2 left-2 flex items-center gap-1">
              <span className="bg-black/60 backdrop-blur-sm px-1.5 py-0.5 rounded text-[8px] font-mono text-white">
                {scene.timestamp_start}
              </span>
              {scene.video_resolution && (
                <span className="bg-black/60 backdrop-blur-sm px-1.5 py-0.5 rounded text-[8px] font-mono text-amber-300">
                  {scene.video_resolution}
                </span>
              )}
            </div>
            {(scene.image_prompt || scene.video_prompt) && (
              <Button
                variant="unstyled"
                onClick={() => onSelectScene(scene)}
                className="absolute top-2 right-2 p-1 bg-black/60 backdrop-blur-sm rounded text-white/70 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                title="View Prompts"
              >
                <Eye size={12} />
              </Button>
            )}
          </div>
          <div className="p-2.5 space-y-1.5">
            <div className="flex items-center justify-between gap-1">
              <span className="text-[9px] font-bold uppercase text-muted-foreground">
                Scene {i + 1}
              </span>
              {scene.eval_status && (
                <EvalStatusPill status={scene.eval_status} regenCount={scene.regen_count} />
              )}
            </div>
            <p className="text-[10px] text-muted-foreground line-clamp-2">
              {scene.visual_description}
            </p>
            {scene.speaker_notes && (
              <p
                className="text-[9px] italic text-accent-dark line-clamp-1"
                title={scene.speaker_notes}
              >
                {scene.speaker_notes}
              </p>
            )}
          </div>
        </div>
      ))}
    </div>
  </div>
)
