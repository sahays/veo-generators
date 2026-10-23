import { CheckCircle2, Terminal, RefreshCw, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import type {
  StoryGraphAsset,
  StoryGraphAttributeValue,
  StoryGraphCastEntry,
  StoryGraphScene,
} from '@/types/project'
import type {
  CompiledShotPreview,
  SelectedInspectorItem,
} from './storyGraphStudioTypes'
import { ShotLookPanel } from './ShotLookPanel'
import { RunAttemptsPanel } from './details/RunAttemptsPanel'
import { SceneStepsPanel } from './details/SceneStepsPanel'

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
  <div className="space-y-3">
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
    <div className="space-y-1.5">
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
        <div className="p-2 rounded-lg bg-muted/40 border border-border/60 text-xs">
          <span className="text-[10px] font-mono uppercase text-muted-foreground block">
            9.2 Identity / Wardrobe Specs
          </span>
          <span className="text-foreground font-medium">{item.data.appearance.wardrobe}</span>
        </div>
      )}
      {item.data.asset?.qa_notes && (
        <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs text-emerald-400 space-y-0.5">
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
          size="xs"
          variant="primary"
          icon={CheckCircle2}
          onClick={() => onAppearanceAction(item.id, 'approve')}
          disabled={!!busyAction}
          className="flex-1"
        >
          Approve Reference
        </Button>
        <Button
          size="xs"
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
  productionId,
}: {
  item: Extract<SelectedInspectorItem, { kind: 'video_run' }>
  productionId: string
}) => (
  <div className="space-y-3">
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

    <div className="space-y-1.5">
      <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground block">
        9.1 Continuity Start / Reference / End Frames
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
      <div className="grid grid-cols-2 gap-2 text-[11px] font-mono bg-muted/40 p-2.5 rounded-lg border border-border/60">
        <span>Wardrobe: {formatQaPct(item.data.run.qa_scores.wardrobe_match)}%</span>
        <span>Setting: {formatQaPct(item.data.run.qa_scores.setting_match)}%</span>
        <span>Action: {formatQaPct(item.data.run.qa_scores.action_achieved)}%</span>
        <span>WER: {(item.data.run.qa_scores.dialogue_wer * 100).toFixed(1)}%</span>
        {typeof item.data.run.qa_scores.physics_plausibility === 'number' && (
          <span className="text-emerald-400">
            Physics: {formatQaPct(item.data.run.qa_scores.physics_plausibility)}%
          </span>
        )}
        {typeof item.data.run.qa_scores.object_permanence === 'number' && (
          <span className="text-emerald-400">
            Permanence: {formatQaPct(item.data.run.qa_scores.object_permanence)}%
          </span>
        )}
      </div>
    )}

    <RunAttemptsPanel productionId={productionId} shotId={item.data.run.shot_id} runId={item.data.run.id} />
  </div>
)

export const ShotAndEntityInspectorView = ({
  selectedItem,
  busyAction,
  compiledPreviews,
  onCompilePreview,
  scenes,
  productionId,
}: {
  selectedItem: SelectedInspectorItem
  busyAction: string | null
  compiledPreviews: Record<string, CompiledShotPreview>
  onCompilePreview: (shotId: string) => void
  scenes?: StoryGraphScene[]
  productionId: string
}) =>
  selectedItem.kind === 'shot' ? (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark font-mono font-bold">
          {selectedItem.data.shot.id} · Scene {selectedItem.data.shot.scene_id}
        </span>
        <Button
          size="xs"
          variant="outline"
          icon={busyAction === `compile_${selectedItem.id}` ? Loader2 : Terminal}
          onClick={() => onCompilePreview(selectedItem.id)}
          disabled={!!busyAction}
        >
          Compile Prompt (S7)
        </Button>
      </div>
      <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 space-y-1 font-mono text-[11px]">
        <div>
          Camera: {selectedItem.data.shot.camera?.shot_size} · {selectedItem.data.shot.camera?.angle} ·{' '}
          {selectedItem.data.shot.camera?.movement} · {selectedItem.data.shot.camera?.lens_mm}mm
        </div>
        <div>
          Duration: {selectedItem.data.shot.duration_s}s · Motion:{' '}
          {selectedItem.data.shot.entry_motion_vector || 'locked'} →{' '}
          {selectedItem.data.shot.exit_motion_vector || 'locked'}
        </div>
      </div>
      <ShotLookPanel shot={selectedItem.data.shot} scenes={scenes} />
      {((selectedItem.data.shot.foley_sfx?.length || 0) > 0 ||
        (selectedItem.data.shot.environmental_sfx?.length || 0) > 0 ||
        (selectedItem.data.shot.action_focus_sfx?.length || 0) > 0) && (
        <div className="p-2.5 rounded-lg bg-muted/30 border border-border/50 space-y-1 font-mono text-[10px]">
          <div className="text-foreground font-bold uppercase">Soundscape & Foley Layers</div>
          {selectedItem.data.shot.foley_sfx?.length ? (
            <div>Foley: {selectedItem.data.shot.foley_sfx.join(', ')}</div>
          ) : null}
          {selectedItem.data.shot.environmental_sfx?.length ? (
            <div>Ambience: {selectedItem.data.shot.environmental_sfx.join(', ')}</div>
          ) : null}
          {selectedItem.data.shot.action_focus_sfx?.length ? (
            <div>Action SFX: {selectedItem.data.shot.action_focus_sfx.join(', ')}</div>
          ) : null}
        </div>
      )}
      <div className="space-y-1">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
          Cast Appearances
        </span>
        <div className="flex flex-wrap gap-1.5">
          {(selectedItem.data.shot.cast || []).map((c: StoryGraphCastEntry) => (
            <span
              key={c.entity_id}
              className="px-2 py-0.5 rounded bg-card border border-border text-[10px] font-mono"
            >
              {c.entity_id} [{c.position}] → {c.appearance_id}
            </span>
          ))}
        </div>
      </div>
      {compiledPreviews[selectedItem.id] && (
        <div className="space-y-1">
          <span className="text-[10px] font-mono font-bold uppercase text-emerald-400">
            Compiled Jinja2 Prompt (SHA-256: {compiledPreviews[selectedItem.id].package_hash.slice(0, 12)})
          </span>
          <pre className="p-2.5 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-48 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
            {compiledPreviews[selectedItem.id].compiled_prompt}
          </pre>
        </div>
      )}
    </div>
  ) : selectedItem.kind === 'entity' ? (
    <div className="space-y-3 text-xs">
      <div>
        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
          {selectedItem.data.entity_type} · {selectedItem.data.id}
        </span>
        <h5 className="text-sm font-bold text-foreground mt-1">{selectedItem.data.canonical_name}</h5>
        {(selectedItem.data.aliases?.length ?? 0) > 0 && (
          <p className="text-xs text-muted-foreground">Aliases: {selectedItem.data.aliases?.join(', ')}</p>
        )}
      </div>
      <div className="space-y-1">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
          Canonical Attributes & Provenance
        </span>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(selectedItem.data.attributes || {}).map(
            ([k, v]: [string, StoryGraphAttributeValue]) => (
              <span
                key={k}
                className={cn(
                  'px-2 py-0.5 rounded text-[10px] font-mono border',
                  v.provenance === 'from_text'
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/25',
                )}
              >
                {k}: {v.value} ({v.provenance})
              </span>
            ),
          )}
        </div>
      </div>
    </div>
  ) : selectedItem.kind === 'scene' ? (
    <div className="space-y-2.5 text-xs">
      <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
        Scene {selectedItem.data.scene.index} · {selectedItem.data.scene.id}
      </span>
      <h5 className="text-sm font-bold text-foreground">{selectedItem.data.scene.heading}</h5>
      <p className="text-muted-foreground leading-relaxed">{selectedItem.data.scene.summary}</p>
      <SceneStepsPanel productionId={productionId} scene={selectedItem.data.scene} />
    </div>
  ) : null
