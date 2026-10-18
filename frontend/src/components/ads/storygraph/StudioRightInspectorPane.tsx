import { useState } from 'react'
import {
  CheckCircle2,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Sliders,
  Clock,
  Cpu,
  ChevronDown,
  ChevronRight,
  Layers,
  ShieldCheck,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import type {
  StoryGraphData,
  StoryGraphGate,
  StoryGraphStageRun,
} from '@/types/project'
import {
  PIPELINE_SUB_STAGES,
  type ActiveStepId,
  type CompiledShotPreview,
  type MacroStepCardDef,
  type SelectedInspectorItem,
} from './storyGraphStudioTypes'
import {
  AppearanceInspectorView,
  ShotAndEntityInspectorView,
  VideoRunInspectorView,
} from './StudioInspectorItemViews'

const CollapsibleDrawer = ({
  title,
  badge,
  isOpen,
  onToggle,
  children,
}: {
  title: string
  badge?: string
  isOpen: boolean
  onToggle: () => void
  children: React.ReactNode
}) => (
  <div className="rounded-xl border border-border/70 bg-card/60 overflow-hidden">
    <Button
      variant="unstyled"
      type="button"
      onClick={onToggle}
      className="w-full px-3.5 py-2.5 flex items-center justify-between gap-2 bg-muted/35 hover:bg-muted/60 transition-colors text-left"
    >
      <div className="flex items-center gap-2 min-w-0">
        {isOpen ? (
          <ChevronDown size={14} className="text-accent-dark shrink-0" />
        ) : (
          <ChevronRight size={14} className="text-muted-foreground shrink-0" />
        )}
        <span className="text-xs font-heading font-bold uppercase tracking-wider text-foreground truncate">
          {title}
        </span>
      </div>
      {badge && (
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold shrink-0">
          {badge}
        </span>
      )}
    </Button>
    {isOpen && <div className="p-3.5 space-y-3 border-t border-border/50">{children}</div>}
  </div>
)

const KitchenStageQaAndTelemetry = ({
  storyGraph,
  latestStageRunByStage,
  completedStages,
  gatesById,
  activeStep,
  canWrite,
  busyAction,
  isRunningPipeline,
  onSelectStepGroup,
  onRunStage,
}: {
  storyGraph?: StoryGraphData
  latestStageRunByStage: Record<string, StoryGraphStageRun>
  completedStages: Set<string>
  gatesById: Record<string, StoryGraphGate>
  activeStep: ActiveStepId
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onSelectStepGroup: (group: ActiveStepId) => void
  onRunStage: (stageId: string) => void
}) => {
  const qaReports = storyGraph?.stage_qa_reports || []
  return (
    <div className="space-y-3">
      {qaReports.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-400 flex items-center gap-1">
            <ShieldCheck size={12} /> O(V+E) Shift-Left Stage QA Reports ({qaReports.length})
          </span>
          <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
            {qaReports.map((rep, idx) => (
              <div
                key={`${rep.stage}_${rep.iteration}_${idx}`}
                className="p-2 rounded-lg bg-muted/40 border border-border/60 text-[10px] font-mono space-y-0.5"
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-foreground">
                    {rep.stage} · {rep.agent_role} (Iter #{rep.iteration})
                  </span>
                  <span className={rep.passed ? 'text-emerald-400 font-bold' : 'text-amber-400 font-bold'}>
                    {(rep.score * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-muted-foreground">{rep.summary}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
          <Cpu size={12} className="text-accent-dark" /> Agent Stage Execution Kitchen
        </span>
        <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
          {PIPELINE_SUB_STAGES.map((st) => {
            const sr = latestStageRunByStage[st.id]
            const isDone = completedStages.has(st.id)
            const isFailed = sr?.status === 'failed' || !!sr?.error
            const gateObj = st.gate ? gatesById[st.gate] : null
            return (
              <div
                key={st.id}
                onClick={() => onSelectStepGroup(st.stepGroup)}
                className={cn(
                  'cursor-pointer p-2 rounded-xl border transition-all flex items-center justify-between gap-2',
                  isFailed
                    ? 'bg-red-500/15 border-red-500/50'
                    : activeStep === st.stepGroup
                      ? 'bg-accent/10 border-accent/40'
                      : isDone
                        ? 'bg-muted/30 border-border/60 hover:border-emerald-500/40'
                        : 'bg-muted/15 border-border/40',
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    {isFailed ? (
                      <AlertTriangle size={12} className="text-red-400 shrink-0" />
                    ) : isDone ? (
                      <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
                    ) : (
                      <Clock size={12} className="text-muted-foreground shrink-0" />
                    )}
                    <span className="text-[11px] font-mono font-bold text-foreground">
                      {st.short} · {st.label}
                    </span>
                    {st.gate && (
                      <span
                        className={cn(
                          'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold',
                          gateObj?.decision === 'approved'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-amber-500/20 text-amber-400',
                        )}
                      >
                        {st.gate}
                      </span>
                    )}
                  </div>
                  <div className="text-[10px] font-mono text-muted-foreground truncate mt-0.5">
                    {st.role}
                    {sr?.duration_s ? ` · ${sr.duration_s.toFixed(1)}s` : ''}
                    {sr?.images_generated ? ` · ${sr.images_generated} imgs` : ''}
                    {sr?.videos_generated ? ` · ${sr.videos_generated} clips` : ''}
                  </div>
                </div>
                {canWrite && (
                  <div onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="xs"
                      variant="ghost"
                      icon={busyAction === st.id ? Loader2 : RefreshCw}
                      onClick={() => onRunStage(st.id)}
                      disabled={!!busyAction || isRunningPipeline}
                      title={`Run ${st.id}`}
                    >
                      Run
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export const StudioRightInspectorPane = ({
  selectedItem,
  onClearSelection,
  canWrite,
  busyAction,
  isRunningPipeline,
  compiledPreviews,
  onCompilePreview,
  onAppearanceAction,
  latestStageRunByStage,
  completedStages,
  gatesById,
  activeStep,
  activeAgentCard,
  storyGraph,
  panelSizePct = 35,
  onChangePanelSizePct,
  onSelectStepGroup,
  onRunStage,
}: {
  selectedItem: SelectedInspectorItem | null
  onClearSelection: () => void
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  compiledPreviews: Record<string, CompiledShotPreview>
  onCompilePreview: (shotId: string) => void
  onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
  latestStageRunByStage: Record<string, StoryGraphStageRun>
  completedStages: Set<string>
  gatesById: Record<string, StoryGraphGate>
  activeStep: ActiveStepId
  activeAgentCard?: MacroStepCardDef
  storyGraph?: StoryGraphData
  panelSizePct?: number
  onChangePanelSizePct?: (pct: number) => void
  onSelectStepGroup: (group: ActiveStepId) => void
  onRunStage: (stageId: string) => void
}) => {
  const [openInputs, setOpenInputs] = useState(true)
  const [openKitchen, setOpenKitchen] = useState(true)
  const [openOutputs, setOpenOutputs] = useState(true)

  const styleGuide = storyGraph?.style_guide

  return (
    <div className="space-y-4 w-full">
      <div className="glass rounded-2xl p-5 border border-border/80 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
          <div className="flex items-center gap-2">
            <Sliders size={15} className="text-accent-dark" />
            <h4 className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
              {selectedItem
                ? `Context Panel · ${selectedItem.kind.toUpperCase()}`
                : `Context Panel · ${activeAgentCard?.title || 'Agent Crew'}`}
            </h4>
          </div>
          <div className="flex items-center gap-1.5">
            {onChangePanelSizePct &&
              [30, 40, 50].map((pct) => (
                <Button
                  key={pct}
                  size="xs"
                  variant={panelSizePct === pct ? 'secondary' : 'ghost'}
                  onClick={() => onChangePanelSizePct(pct)}
                  title={`Resize context panel to ${pct}%`}
                >
                  {pct}%
                </Button>
              ))}
            {selectedItem && (
              <Button size="xs" variant="ghost" onClick={onClearSelection}>
                Reset
              </Button>
            )}
          </div>
        </div>

        <CollapsibleDrawer
          title="1. Inputs (Upstream Context & Presets)"
          badge={activeAgentCard?.stepNum || 'INPUTS'}
          isOpen={openInputs}
          onToggle={() => setOpenInputs((v) => !v)}
        >
          <p className="text-xs text-muted-foreground leading-relaxed">
            {activeAgentCard?.inputsSummary ||
              'Story concept, canonical entities, and creative presets.'}
          </p>
          {styleGuide && (
            <div className="flex flex-wrap gap-1.5 pt-1 text-[10px] font-mono">
              {styleGuide.visual_style_preset && (
                <span className="px-2 py-0.5 rounded bg-muted border border-border">
                  Visual: {styleGuide.visual_style_preset}
                </span>
              )}
              {styleGuide.color_palette_preset && (
                <span className="px-2 py-0.5 rounded bg-muted border border-border">
                  Palette: {styleGuide.color_palette_preset}
                </span>
              )}
              {styleGuide.director_style_preset && (
                <span className="px-2 py-0.5 rounded bg-muted border border-border">
                  Director: {styleGuide.director_style_preset}
                </span>
              )}
              {styleGuide.screenplay_style_preset && (
                <span className="px-2 py-0.5 rounded bg-muted border border-border">
                  Screenplay: {styleGuide.screenplay_style_preset}
                </span>
              )}
              {styleGuide.music_style_preset && (
                <span className="px-2 py-0.5 rounded bg-muted border border-border">
                  Sound: {styleGuide.music_style_preset}
                </span>
              )}
            </div>
          )}
        </CollapsibleDrawer>

        <CollapsibleDrawer
          title="2. The Kitchen (Intermediate Files & QA)"
          badge={`${(storyGraph?.stage_qa_reports || []).length} QA`}
          isOpen={openKitchen}
          onToggle={() => setOpenKitchen((v) => !v)}
        >
          <p className="text-xs text-muted-foreground leading-relaxed">
            {activeAgentCard?.kitchenSummary ||
              'Intermediate reasoning, O(V+E) graph checks, and prompt compilation.'}
          </p>
          <KitchenStageQaAndTelemetry
            storyGraph={storyGraph}
            latestStageRunByStage={latestStageRunByStage}
            completedStages={completedStages}
            gatesById={gatesById}
            activeStep={activeStep}
            canWrite={canWrite}
            busyAction={busyAction}
            isRunningPipeline={isRunningPipeline}
            onSelectStepGroup={onSelectStepGroup}
            onRunStage={onRunStage}
          />
        </CollapsibleDrawer>

        <CollapsibleDrawer
          title="3. Outputs (Deliverables & Node Inspector)"
          badge={selectedItem ? selectedItem.kind.toUpperCase() : activeAgentCard?.metricPrimary}
          isOpen={openOutputs}
          onToggle={() => setOpenOutputs((v) => !v)}
        >
          <p className="text-xs text-muted-foreground leading-relaxed">
            {activeAgentCard?.outputsSummary || 'Canonical StoryGraph deliverables.'}
          </p>
          {selectedItem?.kind === 'appearance' && (
            <AppearanceInspectorView
              item={selectedItem}
              canWrite={canWrite}
              busyAction={busyAction}
              onAppearanceAction={onAppearanceAction}
            />
          )}
          {selectedItem?.kind === 'video_run' && <VideoRunInspectorView item={selectedItem} />}
          {selectedItem &&
            (selectedItem.kind === 'shot' ||
              selectedItem.kind === 'entity' ||
              selectedItem.kind === 'scene') && (
              <ShotAndEntityInspectorView
                selectedItem={selectedItem}
                busyAction={busyAction}
                compiledPreviews={compiledPreviews}
                onCompilePreview={onCompilePreview}
              />
            )}
          {!selectedItem && (
            <div className="p-3 rounded-lg bg-muted/30 border border-border/50 text-[11px] text-muted-foreground flex items-center gap-2">
              <Layers size={14} className="text-accent-dark shrink-0" />
              <span>
                Click any Entity, Scene, Reference Sheet, Directed Shot, or Video Clip in the main workspace to inspect its deep output telemetry here.
              </span>
            </div>
          )}
        </CollapsibleDrawer>
      </div>
    </div>
  )
}
