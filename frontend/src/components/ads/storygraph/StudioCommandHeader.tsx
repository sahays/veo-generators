import {
  CheckCircle2,
  XCircle,
  Sparkles,
  Film,
  RefreshCw,
  Loader2,
  Play,
  AlertTriangle,
  GitBranch,
  Orbit,
  Layers,
  ChevronRight,
  ChevronDown,
  Clock,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import type { StoryGraphGate, StoryGraphStageRun } from '@/types/project'
import type {
  ActiveStepId,
  MacroStepCardDef,
  SelectedInspectorItem,
} from './storyGraphStudioTypes'

export const StrictFailureBanner = ({
  activeError,
  currentStage,
  canWrite,
  busyAction,
  isRunningPipeline,
  onRetryStage,
  onDismiss,
}: {
  activeError: string
  currentStage?: string
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRetryStage: (stage: string) => void
  onDismiss: () => void
}) => (
  <div className="rounded-xl border-2 border-red-500/60 bg-red-500/15 p-5 flex flex-wrap items-center justify-between gap-4">
    <div className="flex items-start gap-3">
      <AlertTriangle size={20} className="text-red-400 shrink-0 mt-0.5" />
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-red-500/30 text-red-200 text-[10px] font-mono font-bold uppercase">
            Pipeline Halted — Strict Failure Mode (No Silent Fallback)
          </span>
          {currentStage && (
            <span className="text-[11px] font-mono text-red-300">Stage: {currentStage}</span>
          )}
        </div>
        <p className="text-xs font-mono text-red-200 break-all">{activeError}</p>
      </div>
    </div>
    <div className="flex items-center gap-2">
      {canWrite && currentStage && (
        <Button
          size="xs"
          variant="primary"
          icon={busyAction === currentStage ? Loader2 : RefreshCw}
          onClick={() => onRetryStage(currentStage)}
          disabled={!!busyAction || isRunningPipeline}
        >
          Retry {currentStage}
        </Button>
      )}
      <Button variant="ghost" size="xs" onClick={onDismiss}>
        Dismiss
      </Button>
    </div>
  </div>
)

export const GateControlBar = ({
  gateId, stageId, stageLabel, gate, canWrite, gateNote, onGateNoteChange,
  busyAction, isRunningPipeline, onGateDecision, onRunStage,
}: {
  gateId: 'G1' | 'G2' | 'G3'; stageId: string; stageLabel: string; gate?: StoryGraphGate
  canWrite: boolean; gateNote: string; onGateNoteChange: (val: string) => void
  busyAction: string | null; isRunningPipeline: boolean
  onGateDecision: (gateId: 'G1' | 'G2' | 'G3', decision: 'approve' | 'reject') => void
  onRunStage: (stageId: string) => void
}) => (
  <div
    className={cn(
      'rounded-xl border p-4 flex flex-wrap items-center justify-between gap-3',
      (gate?.decision || 'pending') === 'approved'
        ? 'bg-emerald-500/10 border-emerald-500/30'
        : (gate?.decision || 'pending') === 'rejected'
          ? 'bg-red-500/10 border-red-500/30'
          : 'bg-amber-500/10 border-amber-500/40',
    )}
  >
    <div className="flex flex-wrap items-center gap-2.5">
      <span
        className={cn(
          'px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase',
          (gate?.decision || 'pending') === 'approved'
            ? 'bg-emerald-500/20 text-emerald-400'
            : (gate?.decision || 'pending') === 'rejected'
              ? 'bg-red-500/20 text-red-400'
              : 'bg-amber-500/20 text-amber-400',
        )}
      >
        Gate {gateId}: {gate?.decision || 'pending'}
      </span>
      <span className="text-xs font-medium text-foreground">
        Review {stageLabel} outputs — approve to unlock downstream stages, reject, or regenerate {stageId}.
      </span>
    </div>
    {canWrite && (
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={gateNote}
          onChange={(e) => onGateNoteChange(e.target.value)}
          placeholder={`Reviewer notes for ${gateId}...`}
          className="h-8 text-xs w-48 bg-card border-border"
        />
        <Button size="xs" variant="primary" icon={busyAction === `gate_${gateId}_approve` ? Loader2 : CheckCircle2} onClick={() => onGateDecision(gateId, 'approve')} disabled={!!busyAction || isRunningPipeline}>
          Approve {gateId}
        </Button>
        <Button size="xs" variant="outline" icon={busyAction === `gate_${gateId}_reject` ? Loader2 : XCircle} onClick={() => onGateDecision(gateId, 'reject')} disabled={!!busyAction || isRunningPipeline}>
          Reject {gateId}
        </Button>
        <Button size="xs" variant="ghost" icon={busyAction === stageId ? Loader2 : RefreshCw} onClick={() => onRunStage(stageId)} disabled={!!busyAction || isRunningPipeline}>
          Regenerate {stageId}
        </Button>
      </div>
    )}
  </div>
)

export const MacroStepCardItem = ({
  card, isSelected, allDone, anyFailed, gateObj, onSelect,
}: {
  card: MacroStepCardDef; isSelected: boolean; allDone: boolean; anyFailed: boolean
  gateObj?: StoryGraphGate | null; onSelect: () => void
}) => (
  <div
    onClick={onSelect}
    className={cn(
      'cursor-pointer rounded-2xl border p-5 transition-all flex flex-col justify-between gap-4 relative group min-w-0',
      anyFailed
        ? 'bg-red-500/15 border-red-500/60 hover:border-red-400'
        : isSelected
          ? 'ring-2 ring-accent bg-accent/15 border-accent shadow-lg'
          : allDone
            ? 'bg-card/90 border-emerald-500/35 hover:border-emerald-500/70 hover:bg-card'
            : 'bg-card/50 border-border/70 hover:border-accent/50',
    )}
  >
    <div className="space-y-3 min-w-0">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div
            className={cn(
              'w-9 h-9 rounded-xl flex items-center justify-center border shrink-0 mt-0.5',
              anyFailed
                ? 'bg-red-500/20 border-red-500/40 text-red-300'
                : isSelected
                  ? 'bg-accent/25 border-accent/50 text-accent-dark'
                  : allDone
                    ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                    : 'bg-muted border-border text-muted-foreground',
            )}
          >
            <card.icon size={17} />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-muted-foreground">{card.stepNum}</span>
              <span className="text-[11px] font-mono text-accent-dark font-bold break-words">({card.stages.join(' · ')})</span>
            </div>
            <h4 className="text-base font-heading font-bold text-foreground leading-snug break-words">{card.title}</h4>
          </div>
        </div>
        {anyFailed ? (
          <AlertTriangle size={17} className="text-red-400 shrink-0 mt-1" />
        ) : allDone ? (
          <CheckCircle2 size={17} className="text-emerald-400 shrink-0 mt-1" />
        ) : (
          <Clock size={16} className="text-muted-foreground shrink-0 mt-1" />
        )}
      </div>
      <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">{card.summaryText}</p>
    </div>
    <div className="pt-3.5 border-t border-border/50 space-y-2">
      <div className="flex flex-col items-start gap-1.5">
        <span className="text-xs font-mono font-bold text-foreground">{card.metricPrimary}</span>
        {card.gate && (
          <span
            className={cn(
              'px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase',
              gateObj?.decision === 'approved'
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : gateObj?.decision === 'rejected'
                  ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                  : 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
            )}
          >
            Gate {card.gate}: {gateObj?.decision || 'pending'}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-muted-foreground">
        <span className="break-words">{card.metricSecondary}</span>
        <ChevronRight size={14} className={cn('shrink-0 transition-transform', isSelected ? 'translate-x-0.5 text-accent-dark' : 'group-hover:translate-x-0.5')} />
      </div>
    </div>
  </div>
)

export const StudioCommandHeader = ({
  completedStages, pendingGate, show3DGraph, onToggle3DGraph, expandAllSteps, onToggleExpandAll,
  canWrite, isRunningPipeline, busyAction, onRunForward, macroStepCards, activeStep,
  latestStageRunByStage, gatesById, onSelectCard,
}: {
  completedStages: Set<string>; pendingGate: string | null; show3DGraph: boolean; onToggle3DGraph: () => void
  expandAllSteps: boolean; onToggleExpandAll: () => void; canWrite: boolean; isRunningPipeline: boolean
  busyAction: string | null; onRunForward: (autoApprove: boolean) => void; macroStepCards: MacroStepCardDef[]
  activeStep: ActiveStepId; latestStageRunByStage: Record<string, StoryGraphStageRun>
  gatesById: Record<string, StoryGraphGate>; onSelectCard: (card: MacroStepCardDef) => void
}) => (
  <div className="glass rounded-2xl p-6 md:p-7 border border-border/80 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex flex-wrap items-center gap-3.5">
        <div className="w-10 h-10 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent-dark shrink-0">
          <GitBranch size={19} />
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h3 className="text-sm font-heading font-bold uppercase tracking-wider text-foreground">
              Story-to-Video Pipeline Stages
            </h3>
            <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[11px] font-mono font-bold">
              {completedStages.size - (completedStages.has('S0_INGEST') ? 1 : 0)}/10 Stages Complete
            </span>
            {pendingGate && (
              <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 text-[11px] font-mono font-bold">
                Awaiting Gate {pendingGate} Approval
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Select any pipeline step card below to inspect its intermediate outputs, or click an artifact to view deep telemetry in the right inspector pane.
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <Button size="xs" variant={show3DGraph ? 'secondary' : 'outline'} icon={Orbit} onClick={onToggle3DGraph}>
          {show3DGraph ? 'Hide 3D Constellation' : '3D StoryGraph View'}
        </Button>
        <Button size="xs" variant={expandAllSteps ? 'secondary' : 'outline'} icon={Layers} onClick={onToggleExpandAll}>
          {expandAllSteps ? 'Focused Step Mode' : 'Expand All Stages'}
        </Button>
        {canWrite && (
          <>
            <Button size="xs" variant="outline" icon={isRunningPipeline ? Loader2 : Play} onClick={() => onRunForward(false)} disabled={isRunningPipeline || !!busyAction}>
              {isRunningPipeline ? 'Running Step...' : 'Step Mode (Next Gate)'}
            </Button>
            <Button size="xs" variant="primary" icon={isRunningPipeline ? Loader2 : Sparkles} onClick={() => onRunForward(true)} disabled={isRunningPipeline || !!busyAction}>
              {isRunningPipeline ? 'Auto-Running Pipeline...' : 'Auto Mode (Auto-Approve All & Final Cut)'}
            </Button>
          </>
        )}
      </div>
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      {macroStepCards.map((card) => (
        <MacroStepCardItem
          key={card.id}
          card={card}
          isSelected={!expandAllSteps && activeStep === card.id}
          allDone={card.stages.every((st) => completedStages.has(st))}
          anyFailed={card.stages.some((st) => latestStageRunByStage[st]?.status === 'failed' || !!latestStageRunByStage[st]?.error)}
          gateObj={card.gate ? gatesById[card.gate] : null}
          onSelect={() => onSelectCard(card)}
        />
      ))}
    </div>
  </div>
)

export const MasterCutQuickBanner = ({
  finalVideoUrl,
  clipCount,
  showMasterCutBanner,
  onToggleBanner,
  onInspectClips,
}: {
  finalVideoUrl: string
  clipCount: number
  showMasterCutBanner: boolean
  onToggleBanner: () => void
  onInspectClips: () => void
}) => (
  <div className="glass rounded-xl p-4 border border-emerald-500/30 bg-emerald-500/5 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2.5">
        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-mono font-bold uppercase">
          Master Final Cut Ready
        </span>
        <span className="text-xs font-semibold text-foreground">
          Stitched {clipCount}-Clip Master Output (S10_ASSEMBLE)
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Button size="xs" variant="outline" icon={Film} onClick={onInspectClips}>
          Inspect All {clipCount} Clips
        </Button>
        <Button
          size="xs"
          variant="ghost"
          icon={showMasterCutBanner ? ChevronDown : ChevronRight}
          onClick={onToggleBanner}
        >
          {showMasterCutBanner ? 'Minimize Player' : 'Show Player'}
        </Button>
      </div>
    </div>
    {showMasterCutBanner && (
      <div className="aspect-video max-w-3xl mx-auto rounded-xl overflow-hidden bg-black border border-border">
        <video
          key={finalVideoUrl}
          controls
          preload="metadata"
          src={finalVideoUrl}
          className="w-full h-full"
        />
      </div>
    )}
  </div>
)

export type { SelectedInspectorItem }
