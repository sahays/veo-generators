// Shared subcomponents for SceneItemGrid, SceneItemList, RefinePromptView, and ProductionSummary.

import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Film,
  Loader2,
  MessageSquareQuote,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type {
  PipelineStepLog,
  RenderQuality,
  Scene,
  UsageMetrics,
  VideoResolution,
} from '@/types/project'

export interface SceneItemHandlers {
  handleToggle: (updates: any) => void
  handleTextChange: (updates: any) => void
  handleGenerateFrame: (promptData?: any) => void | Promise<void>
  handleGenerateVideo: (promptData?: any) => void | Promise<void>
}

export const AudioToggle = ({
  checked,
  onChange,
  disabled,
  icon,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled: boolean
  icon: React.ReactNode
  label: string
}) => (
  <label className="flex items-center gap-1.5 cursor-pointer select-none">
    <input
      type="checkbox"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      disabled={disabled}
      className="accent-accent w-3.5 h-3.5"
    />
    {icon}
    <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
      {label}
    </span>
  </label>
)

export const StatusIcon = ({
  status,
  videoResolution,
  evalStatus,
}: {
  status?: string
  videoResolution?: string
  evalStatus?: string
}) => {
  return (
    <span className="inline-flex items-center gap-1">
      {(status === 'generating_frame' || status === 'generating') && (
        <Loader2 size={10} className="animate-spin text-amber-500" />
      )}
      {status === 'completed' && (
        <CheckCircle2 size={10} className="text-emerald-500" />
      )}
      {status === 'failed' && (
        <AlertCircle size={10} className="text-red-500" />
      )}
      {videoResolution && (
        <span className="px-1 py-0.2 rounded bg-muted text-[8px] font-mono font-bold text-foreground border border-border">
          {videoResolution}
        </span>
      )}
      {evalStatus === 'passed' && (
        <ShieldCheck size={10} className="text-emerald-500" />
      )}
      {evalStatus === 'flagged' && (
        <ShieldAlert size={10} className="text-amber-500" />
      )}
      {evalStatus === 'regenerated' && (
        <RefreshCw size={10} className="text-sky-500" />
      )}
    </span>
  )
}

export const StatusBadge = ({
  status,
  videoResolution,
  evalStatus,
}: {
  status?: string
  videoResolution?: string
  evalStatus?: string
}) => {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {status === 'generating_frame' && (
        <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-amber-500">
          <Loader2 size={10} className="animate-spin" /> Generating Frame
        </span>
      )}
      {status === 'generating' && (
        <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-amber-500">
          <Loader2 size={10} className="animate-spin" /> Generating Video
        </span>
      )}
      {status === 'completed' && (
        <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-emerald-500">
          <CheckCircle2 size={10} /> Done
        </span>
      )}
      {status === 'failed' && (
        <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-red-500">
          <AlertCircle size={10} /> Failed
        </span>
      )}
      {videoResolution && (
        <span className="px-1.5 py-0.5 rounded bg-muted text-[9px] font-mono font-semibold text-foreground border border-border">
          {videoResolution}
        </span>
      )}
      {evalStatus && <EvalStatusPill status={evalStatus} />}
    </span>
  )
}

export const EvalStatusPill = ({
  status,
  regenCount,
}: {
  status?: string
  regenCount?: number
}) => {
  if (!status) return null
  if (status === 'passed') {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-[9px] font-bold uppercase tracking-wider">
        <ShieldCheck size={10} /> Eval Passed
      </span>
    )
  }
  if (status === 'flagged') {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20 text-[9px] font-bold uppercase tracking-wider">
        <AlertTriangle size={10} /> Flagged
      </span>
    )
  }
  if (status === 'regenerating') {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20 text-[9px] font-bold uppercase tracking-wider">
        <Loader2 size={10} className="animate-spin" /> Regenerating
      </span>
    )
  }
  if (status === 'regenerated') {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 text-[9px] font-bold uppercase tracking-wider">
        <RefreshCw size={10} /> Regenerated{regenCount && regenCount > 0 ? ` (${regenCount}x)` : ''}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-muted-foreground border border-border text-[9px] font-bold uppercase tracking-wider">
      {status}
    </span>
  )
}

export const RenderQualityBadge = ({
  quality,
  resolution,
}: {
  quality?: RenderQuality | string
  resolution?: VideoResolution | string
}) => {
  const isFinal = quality === 'final' || resolution === '720p' || resolution === '1080p'
  if (isFinal) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-500 border border-emerald-500/25 text-[10px] font-bold uppercase tracking-wider">
        <Sparkles size={11} /> Final ({resolution || '720p'} HD)
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-500 border border-amber-500/25 text-[10px] font-bold uppercase tracking-wider">
      <Film size={11} /> Draft ({resolution || '360p'} Omni 1.1)
    </span>
  )
}

export const StepStatusIcon = ({ status }: { status: PipelineStepLog['status'] }) => {
  if (status === 'running') {
    return <Loader2 size={14} className="animate-spin text-amber-500 shrink-0" />
  }
  if (status === 'completed') {
    return <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />
  }
  if (status === 'failed') {
    return <AlertCircle size={14} className="text-red-500 shrink-0" />
  }
  return <Circle size={12} className="text-muted-foreground/50 shrink-0" />
}

export const StepUsageBadges = ({ usage }: { usage?: UsageMetrics }) => {
  if (!usage) return null
  const inTok = usage.input_tokens || 0
  const outTok = usage.output_tokens || 0
  const imgGen = usage.image_generations || 0
  const imgOutTok = usage.image_output_tokens || 0
  const veoSec = usage.veo_seconds || 0
  const veoVids = usage.veo_videos || 0
  const transcoderMin = usage.transcoder_minutes || 0
  const costUsd = usage.cost_usd || 0

  if (inTok + outTok === 0 && imgGen === 0 && veoSec === 0 && transcoderMin === 0 && costUsd === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-mono">
      {inTok + outTok > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-muted/80 text-muted-foreground border border-border">
          {inTok.toLocaleString()} in / {outTok.toLocaleString()} out tok
        </span>
      )}
      {imgGen > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500 border border-amber-500/20">
          {imgGen} frames ({imgOutTok.toLocaleString()} img tok)
        </span>
      )}
      {veoSec > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-500 border border-amber-500/10">
          {veoVids} clips • {veoSec}s
        </span>
      )}
      {transcoderMin > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
          {transcoderMin.toFixed(2)}m transcode
        </span>
      )}
      {costUsd > 0 && (
        <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark font-semibold border border-accent/20">
          ${costUsd.toFixed(4)}
        </span>
      )}
    </div>
  )
}

export const SceneMetaBanner = ({
  scene,
  index,
  compact = false,
}: {
  scene: Scene
  index: number
  compact?: boolean
}) => {
  const hasMeta =
    !!scene.video_resolution ||
    !!scene.eval_status ||
    !!scene.speaker_notes ||
    !!scene.eval_feedback

  if (!hasMeta) return null

  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 rounded-t-xl border border-b-0 border-border/60 bg-muted/30 px-3.5 py-2',
        compact && 'px-2.5 py-1.5 rounded-lg border-b',
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
            Scene {index + 1}
          </span>
          {scene.video_resolution && (
            <span
              className={cn(
                'px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase border',
                scene.video_resolution === '720p' || scene.video_resolution === '1080p'
                  ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                  : 'bg-amber-500/10 text-amber-500 border-amber-500/20',
              )}
            >
              {scene.video_resolution}
            </span>
          )}
          {scene.eval_status && (
            <EvalStatusPill status={scene.eval_status} regenCount={scene.regen_count} />
          )}
        </div>
        {scene.speaker_notes && !compact && (
          <div className="flex items-center gap-1.5 text-[11px] text-foreground/90 bg-card/70 px-2 py-0.5 rounded border border-border/60">
            <MessageSquareQuote size={12} className="text-accent shrink-0" />
            <span className="font-medium text-muted-foreground">Speaker Notes:</span>
            <span className="italic">{scene.speaker_notes}</span>
          </div>
        )}
      </div>
      {scene.speaker_notes && compact && (
        <p className="text-[10px] text-muted-foreground line-clamp-1 italic" title={scene.speaker_notes}>
          Speaker: {scene.speaker_notes}
        </p>
      )}
      {scene.eval_feedback && (
        <div className="text-[11px] text-amber-500/90 bg-amber-500/5 border border-amber-500/20 rounded px-2.5 py-1 flex items-start gap-1.5">
          <AlertTriangle size={12} className="shrink-0 mt-0.5" />
          <span>{scene.eval_feedback}</span>
        </div>
      )}
    </div>
  )
}
