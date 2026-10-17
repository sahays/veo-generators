import {
  CheckCircle2,
  Terminal,
  RefreshCw,
  Loader2,
  AlertTriangle,
  Sliders,
  Clock,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import type {
  StoryGraphAsset,
  StoryGraphAttributeValue,
  StoryGraphCastEntry,
  StoryGraphGate,
  StoryGraphStageRun,
} from '@/types/project'
import {
  PIPELINE_SUB_STAGES,
  type ActiveStepId,
  type CompiledShotPreview,
  type SelectedInspectorItem,
} from './storyGraphStudioTypes'

export const AppearanceInspectorView = ({
  item,
  canWrite,
  busyAction,
  onAppearanceAction,
}: {
  item: Extract<SelectedInspectorItem, { kind: 'appearance' }>
  canWrite: boolean
  busyAction: string | null
  onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
}) => (
  <div className="space-y-4">
    <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border">
      {item.data.asset?.signed_url ? (
        <img
          src={item.data.asset.signed_url}
          alt={item.id}
          className="w-full h-full object-contain"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">
          No image asset
        </div>
      )}
    </div>
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-bold text-foreground">
          {item.data.entity?.canonical_name || item.data.appearance.entity_id}
        </span>
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
          {item.data.appearance.state_label} · v{item.data.appearance.version}
        </span>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        {item.data.appearance.visual_description}
      </p>
      {item.data.appearance.wardrobe && (
        <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 text-xs">
          <span className="text-[10px] font-mono uppercase text-muted-foreground block">
            Wardrobe / Surface Specs
          </span>
          <span className="text-foreground font-medium">{item.data.appearance.wardrobe}</span>
        </div>
      )}
      {item.data.asset?.qa_notes && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs text-emerald-300 space-y-1">
          <span className="text-[10px] font-mono font-bold uppercase block">
            CRITIC VLM Verification
          </span>
          <p>{item.data.asset.qa_notes}</p>
        </div>
      )}
    </div>
    {canWrite && (
      <div className="flex items-center gap-2 pt-2 border-t border-border/50">
        <Button
          size="sm"
          variant="primary"
          icon={CheckCircle2}
          onClick={() => onAppearanceAction(item.id, 'approve')}
          disabled={!!busyAction}
          className="flex-1"
        >
          Approve Reference
        </Button>
        <Button
          size="sm"
          variant="outline"
          icon={RefreshCw}
          onClick={() => onAppearanceAction(item.id, 'regenerate')}
          disabled={!!busyAction}
          className="flex-1"
        >
          Regenerate Sheet
        </Button>
      </div>
    )}
  </div>
)

function formatQaPct(val: number): string {
  return ((val > 1 ? val * 10 : val * 100) || 0).toFixed(0)
}

export const VideoRunInspectorView = ({
  item,
}: {
  item: Extract<SelectedInspectorItem, { kind: 'video_run' }>
}) => (
  <div className="space-y-4">
    {item.data.run.output_video_signed_url && (
      <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border">
        <video
          key={item.data.run.output_video_signed_url}
          controls
          preload="metadata"
          src={item.data.run.output_video_signed_url}
          className="w-full h-full"
        />
      </div>
    )}
    <div className="flex items-center justify-between text-xs font-mono">
      <span className="font-bold text-foreground">
        {item.data.run.shot_id} (Attempt #{item.data.run.attempt})
      </span>
      <span className="text-muted-foreground">
        {item.data.run.model} · seed {item.data.run.seed}
      </span>
    </div>

    <div className="space-y-2">
      <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground block">
        Conditioning Start / Reference / End Frames
      </span>
      <div className="grid grid-cols-3 gap-2">
        {item.data.startAsset?.signed_url && (
          <div className="rounded-lg overflow-hidden border border-amber-500/40 bg-black/50">
            <img
              src={item.data.startAsset.signed_url}
              alt="Start frame"
              className="w-full aspect-video object-cover"
            />
            <p className="px-1.5 py-0.5 text-[9px] font-mono text-amber-300 truncate">
              START FRAME
            </p>
          </div>
        )}
        {(item.data.refAssets || []).map((ra: StoryGraphAsset) => (
          <div key={ra.id} className="rounded-lg overflow-hidden border border-border/60 bg-black/50">
            {ra.signed_url && (
              <img src={ra.signed_url} alt={ra.id} className="w-full aspect-video object-cover" />
            )}
            <p className="px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground truncate">
              {ra.kind}
            </p>
          </div>
        ))}
        {item.data.endAsset?.signed_url && (
          <div className="rounded-lg overflow-hidden border border-emerald-500/40 bg-black/50">
            <img
              src={item.data.endAsset.signed_url}
              alt="End frame"
              className="w-full aspect-video object-cover"
            />
            <p className="px-1.5 py-0.5 text-[9px] font-mono text-emerald-300 truncate">
              END FRAME
            </p>
          </div>
        )}
      </div>
    </div>

    {item.data.run.qa_scores && (
      <div className="grid grid-cols-2 gap-2 text-[11px] font-mono bg-muted/40 p-3 rounded-lg border border-border/60">
        <span>Wardrobe: {formatQaPct(item.data.run.qa_scores.wardrobe_match)}%</span>
        <span>Setting: {formatQaPct(item.data.run.qa_scores.setting_match)}%</span>
        <span>Action: {formatQaPct(item.data.run.qa_scores.action_achieved)}%</span>
        <span>WER: {(item.data.run.qa_scores.dialogue_wer * 100).toFixed(1)}%</span>
      </div>
    )}

    <div className="space-y-1">
      <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
        Compiled Shot Prompt
      </span>
      <pre className="p-3 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-56 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
        {item.data.run.compiled_prompt}
      </pre>
    </div>
  </div>
)

export const ShotAndEntityInspectorView = ({
  selectedItem, busyAction, compiledPreviews, onCompilePreview,
}: {
  selectedItem: SelectedInspectorItem; busyAction: string | null
  compiledPreviews: Record<string, CompiledShotPreview>; onCompilePreview: (shotId: string) => void
}) =>
  selectedItem.kind === 'shot' ? (
    <div className="space-y-4 text-xs">
      <div className="flex items-center justify-between">
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark font-mono font-bold">
          {selectedItem.data.shot.id} · Scene {selectedItem.data.shot.scene_id}
        </span>
        <Button size="xs" variant="outline" icon={busyAction === `compile_${selectedItem.id}` ? Loader2 : Terminal} onClick={() => onCompilePreview(selectedItem.id)} disabled={!!busyAction}>
          Compile Prompt (S7)
        </Button>
      </div>
      <div className="p-3 rounded-lg bg-muted/40 border border-border/60 space-y-1 font-mono text-[11px]">
        <div>
          Camera: {selectedItem.data.shot.camera?.shot_size} · {selectedItem.data.shot.camera?.angle} · {selectedItem.data.shot.camera?.movement} · {selectedItem.data.shot.camera?.lens_mm}mm
        </div>
        <div>Duration: {selectedItem.data.shot.duration_s}s</div>
      </div>
      <div className="space-y-1.5">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Cast Appearances</span>
        <div className="flex flex-wrap gap-1.5">
          {(selectedItem.data.shot.cast || []).map((c: StoryGraphCastEntry) => (
            <span key={c.entity_id} className="px-2 py-1 rounded bg-card border border-border text-[10px] font-mono">
              {c.entity_id} [{c.position}] → {c.appearance_id}
            </span>
          ))}
        </div>
      </div>
      {compiledPreviews[selectedItem.id] && (
        <div className="space-y-1.5">
          <span className="text-[10px] font-mono font-bold uppercase text-emerald-400">
            Compiled Jinja2 Prompt (SHA-256: {compiledPreviews[selectedItem.id].package_hash.slice(0, 12)})
          </span>
          <pre className="p-3 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-60 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
            {compiledPreviews[selectedItem.id].compiled_prompt}
          </pre>
        </div>
      )}
    </div>
  ) : selectedItem.kind === 'entity' ? (
    <div className="space-y-4 text-xs">
      <div>
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
          {selectedItem.data.entity_type} · {selectedItem.data.id}
        </span>
        <h5 className="text-base font-bold text-foreground mt-1">{selectedItem.data.canonical_name}</h5>
        {(selectedItem.data.aliases?.length ?? 0) > 0 && (
          <p className="text-xs text-muted-foreground">Aliases: {selectedItem.data.aliases?.join(', ')}</p>
        )}
      </div>
      <div className="space-y-1.5">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Canonical Attributes & Provenance</span>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(selectedItem.data.attributes || {}).map(([k, v]: [string, StoryGraphAttributeValue]) => (
            <span
              key={k}
              className={cn(
                'px-2 py-1 rounded text-[10px] font-mono border',
                v.provenance === 'from_text' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25' : 'bg-amber-500/10 text-amber-400 border-amber-500/25',
              )}
            >
              {k}: {v.value} ({v.provenance})
            </span>
          ))}
        </div>
      </div>
    </div>
  ) : selectedItem.kind === 'scene' ? (
    <div className="space-y-3 text-xs">
      <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
        Scene {selectedItem.data.scene.index} · {selectedItem.data.scene.id}
      </span>
      <h5 className="text-sm font-bold text-foreground">{selectedItem.data.scene.heading}</h5>
      <p className="text-muted-foreground leading-relaxed">{selectedItem.data.scene.summary}</p>
    </div>
  ) : null

export const StudioRightInspectorPane = ({
  selectedItem, onClearSelection, canWrite, busyAction, isRunningPipeline,
  compiledPreviews, onCompilePreview, onAppearanceAction, latestStageRunByStage,
  completedStages, gatesById, activeStep, onSelectStepGroup, onRunStage,
}: {
  selectedItem: SelectedInspectorItem | null; onClearSelection: () => void; canWrite: boolean
  busyAction: string | null; isRunningPipeline: boolean; compiledPreviews: Record<string, CompiledShotPreview>
  onCompilePreview: (shotId: string) => void; onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
  latestStageRunByStage: Record<string, StoryGraphStageRun>; completedStages: Set<string>
  gatesById: Record<string, StoryGraphGate>; activeStep: ActiveStepId
  onSelectStepGroup: (group: ActiveStepId) => void; onRunStage: (stageId: string) => void
}) => (
  <div className="xl:col-span-4 xl:sticky xl:top-4 space-y-5">
    <div className="glass rounded-2xl p-6 border border-border/80 space-y-5">
      <div className="flex items-center justify-between border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <Sliders size={16} className="text-accent-dark" />
          <h4 className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
            {selectedItem ? `Inspector · ${selectedItem.kind.toUpperCase()}` : 'Pipeline Details & Telemetry'}
          </h4>
        </div>
        {selectedItem && (
          <Button size="xs" variant="ghost" onClick={onClearSelection}>Show Stage Overview</Button>
        )}
      </div>

      {selectedItem?.kind === 'appearance' && (
        <AppearanceInspectorView item={selectedItem} canWrite={canWrite} busyAction={busyAction} onAppearanceAction={onAppearanceAction} />
      )}
      {selectedItem?.kind === 'video_run' && <VideoRunInspectorView item={selectedItem} />}
      {selectedItem && (selectedItem.kind === 'shot' || selectedItem.kind === 'entity' || selectedItem.kind === 'scene') && (
        <ShotAndEntityInspectorView selectedItem={selectedItem} busyAction={busyAction} compiledPreviews={compiledPreviews} onCompilePreview={onCompilePreview} />
      )}

      <div className="pt-3 border-t border-border/60 space-y-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Cpu size={12} className="text-accent-dark" /> 10-Stage Execution Telemetry
          </span>
          <span className="text-[10px] font-mono text-muted-foreground">Click Re-Run to execute any stage</span>
        </div>

        <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
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
                  'cursor-pointer p-2.5 rounded-xl border transition-all flex items-center justify-between gap-2',
                  isFailed ? 'bg-red-500/15 border-red-500/50' : activeStep === st.stepGroup ? 'bg-accent/10 border-accent/40' : isDone ? 'bg-muted/30 border-border/60 hover:border-emerald-500/40' : 'bg-muted/15 border-border/40',
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    {isFailed ? <AlertTriangle size={12} className="text-red-400 shrink-0" /> : isDone ? <CheckCircle2 size={12} className="text-emerald-400 shrink-0" /> : <Clock size={12} className="text-muted-foreground shrink-0" />}
                    <span className="text-[11px] font-mono font-bold text-foreground">{st.short} · {st.label}</span>
                    {st.gate && (
                      <span className={cn('px-1.5 py-0.2 rounded text-[9px] font-mono font-bold', gateObj?.decision === 'approved' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400')}>
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
                    <Button size="xs" variant="ghost" icon={busyAction === st.id ? Loader2 : RefreshCw} onClick={() => onRunStage(st.id)} disabled={!!busyAction || isRunningPipeline} title={`Run ${st.id}`}>
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
  </div>
)
