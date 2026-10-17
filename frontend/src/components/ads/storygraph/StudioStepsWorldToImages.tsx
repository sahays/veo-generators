import {
  CheckCircle2,
  Sparkles,
  User,
  MapPin,
  Box,
  RefreshCw,
  Loader2,
  History,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import type {
  StoryGraphAppearance,
  StoryGraphDialogueLine,
  StoryGraphEntity,
  StoryGraphEvent,
  StoryGraphEventEffect,
  StoryGraphGate,
  StoryGraphScene,
  StoryGraphStateFact,
  StoryGraphStyleGuide,
} from '@/types/project'
import type { DesignFilter, SelectedInspectorItem } from './storyGraphStudioTypes'
import { GateControlBar } from './StudioCommandHeader'

export const StepWorldBibleSection = ({
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
  gateG1,
  gateNoteG1,
  onGateNoteG1Change,
  onGateDecision,
  styleGuide,
  characters,
  locations,
  objects,
  appearances,
  events,
  stateFacts,
  selectedItem,
  onSelectItem,
}: {
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string) => void
  gateG1?: StoryGraphGate
  gateNoteG1: string
  onGateNoteG1Change: (val: string) => void
  onGateDecision: (gateId: 'G1' | 'G2' | 'G3', decision: 'approve' | 'reject') => void
  styleGuide?: StoryGraphStyleGuide | null
  characters: StoryGraphEntity[]
  locations: StoryGraphEntity[]
  objects: StoryGraphEntity[]
  appearances: StoryGraphAppearance[]
  events: StoryGraphEvent[]
  stateFacts: StoryGraphStateFact[]
  selectedItem: SelectedInspectorItem | null
  onSelectItem: (item: SelectedInspectorItem) => void
}) => (
  <div className="glass rounded-2xl p-6 md:p-7 border border-border/80 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
            STEP 01 · S1_EXTRACT
          </span>
          <h3 className="text-base font-heading font-bold text-foreground">
            World Bible, Canonical Entities & Continuity Timeline
          </h3>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Click any Character, Location, or Object card to inspect its attributes, provenance, and
          linked reference sheets in the right pane.
        </p>
      </div>
      {canWrite && (
        <Button
          size="xs"
          variant="outline"
          icon={busyAction === 'S1_EXTRACT' ? Loader2 : RefreshCw}
          onClick={() => onRunStage('S1_EXTRACT')}
          disabled={!!busyAction || isRunningPipeline}
        >
          Regenerate Stage S1
        </Button>
      )}
    </div>

    <GateControlBar
      gateId="G1"
      stageId="S1_EXTRACT"
      stageLabel="World Bible & Canonical Entities"
      gate={gateG1}
      canWrite={canWrite}
      gateNote={gateNoteG1}
      onGateNoteChange={onGateNoteG1Change}
      busyAction={busyAction}
      isRunningPipeline={isRunningPipeline}
      onGateDecision={onGateDecision}
      onRunStage={onRunStage}
    />

    {styleGuide && (
      <Card title="Global StyleGuide (STORY_ARCHITECT)" icon={Sparkles}>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
          <div className="p-3.5 rounded-lg bg-muted/30 border border-border/50">
            <span className="text-[10px] font-bold uppercase text-muted-foreground">
              Visual Medium
            </span>
            <p className="font-medium mt-1 text-foreground">{styleGuide.visual_medium}</p>
          </div>
          <div className="p-3.5 rounded-lg bg-muted/30 border border-border/50">
            <span className="text-[10px] font-bold uppercase text-muted-foreground">
              Lens & Camera Language
            </span>
            <p className="font-medium mt-1 text-foreground">{styleGuide.lens_language}</p>
          </div>
          <div className="p-3.5 rounded-lg bg-muted/30 border border-border/50">
            <span className="text-[10px] font-bold uppercase text-muted-foreground">
              Lighting Rules
            </span>
            <p className="font-medium mt-1 text-foreground">{styleGuide.lighting_rules}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-border/50">
          <span className="text-[10px] font-bold uppercase text-muted-foreground">
            Color Palette:
          </span>
          {(styleGuide.palette || []).map((c: string) => (
            <span
              key={c}
              className="px-2 py-0.5 rounded bg-accent/10 text-accent-dark text-[10px] font-mono"
            >
              {c}
            </span>
          ))}
        </div>
      </Card>
    )}

    <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
      {[
        { title: 'Characters', items: characters, icon: User },
        { title: 'Locations', items: locations, icon: MapPin },
        { title: 'Objects / Hero Props', items: objects, icon: Box },
      ].map((group) => (
        <Card key={group.title} title={`${group.title} (${group.items.length})`} icon={group.icon}>
          <div className="space-y-3">
            {group.items.map((ent: StoryGraphEntity) => {
              const entApps = appearances.filter((a) => a.entity_id === ent.id)
              const thumbUrl = entApps[0]?.assets?.[entApps[0]?.assets.length - 1]?.signed_url
              const isSelected = selectedItem?.kind === 'entity' && selectedItem?.id === ent.id
              return (
                <div
                  key={ent.id}
                  onClick={() => onSelectItem({ kind: 'entity', id: ent.id, data: ent })}
                  className={cn(
                    'cursor-pointer p-3.5 rounded-xl border transition-all flex items-center gap-3.5',
                    isSelected
                      ? 'ring-2 ring-accent bg-accent/15 border-accent'
                      : 'bg-muted/40 border-border/60 hover:border-accent/50',
                  )}
                >
                  {thumbUrl ? (
                    <img
                      src={thumbUrl}
                      alt={ent.canonical_name}
                      className="w-12 h-12 rounded-lg object-cover border border-border shrink-0"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center text-muted-foreground shrink-0">
                      <group.icon size={18} />
                    </div>
                  )}
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div className="flex flex-wrap items-center justify-between gap-1">
                      <span className="text-xs font-bold text-foreground break-words">
                        {ent.canonical_name}
                      </span>
                      <span className="text-[10px] font-mono text-muted-foreground shrink-0">
                        {ent.id}
                      </span>
                    </div>
                    <p className="text-[11px] text-muted-foreground">
                      {Object.keys(ent.attributes || {}).length} attributes · {entApps.length} ref
                      sheets
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      ))}
    </div>

    <Card
      title={`Narrative Event Timeline & State Transitions (${events.length} Events · ${stateFacts.length} StateFacts)`}
      icon={History}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {events.map((ev: StoryGraphEvent) => (
          <div
            key={ev.id}
            className="p-4 rounded-xl bg-muted/30 border border-border/50 space-y-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold">
                Event #{ev.story_order} · {ev.scene_id}
              </span>
              <span className="text-[10px] font-mono text-muted-foreground">{ev.id}</span>
            </div>
            <p className="text-xs font-medium text-foreground leading-relaxed">{ev.summary}</p>
            {(ev.effects || []).length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {(ev.effects || []).map((eff: StoryGraphEventEffect, i: number) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded bg-card border border-border text-[10px] font-mono text-emerald-400"
                  >
                    {eff.entity_id}.{eff.attribute} → {eff.new_value ?? 'null'}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  </div>
)

export const StepScreenplaySection = ({
  scenes,
  events,
  dialogueLines,
  entityMap,
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
  selectedItem,
  onSelectItem,
}: {
  scenes: StoryGraphScene[]
  events: StoryGraphEvent[]
  dialogueLines: StoryGraphDialogueLine[]
  entityMap: Record<string, StoryGraphEntity>
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string) => void
  selectedItem: SelectedInspectorItem | null
  onSelectItem: (item: SelectedInspectorItem) => void
}) => (
  <div className="glass rounded-2xl p-6 md:p-7 border border-border/80 space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
      <div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
            STEP 02 · S2_SCREENPLAY
          </span>
          <h3 className="text-base font-heading font-bold text-foreground">
            Screenplay & Scene Dialogue Scripts ({scenes.length} Scenes · {dialogueLines.length}{' '}
            Dialogue Lines)
          </h3>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Click any scene card to inspect its full action beats, location plate, and dialogue
          breakdown in the right details pane.
        </p>
      </div>
      {canWrite && (
        <Button
          size="xs"
          variant="outline"
          icon={busyAction === 'S2_SCREENPLAY' ? Loader2 : RefreshCw}
          onClick={() => onRunStage('S2_SCREENPLAY')}
          disabled={!!busyAction || isRunningPipeline}
        >
          Regenerate Screenplay (S2)
        </Button>
      )}
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {scenes.map((sc: StoryGraphScene) => {
        const scEvents = events.filter((e) => e.scene_id === sc.id)
        const scDialogues = dialogueLines.filter(
          (dl) => dl.id.includes(sc.id) || (dl.shot_id && dl.shot_id.includes(sc.id)),
        )
        const loc = entityMap[sc.location_id]
        const isSelected = selectedItem?.kind === 'scene' && selectedItem?.id === sc.id
        return (
          <div
            key={sc.id}
            onClick={() =>
              onSelectItem({
                kind: 'scene',
                id: sc.id,
                data: { scene: sc, events: scEvents, dialogues: scDialogues, loc },
              })
            }
            className={cn(
              'cursor-pointer rounded-2xl p-5 border transition-all space-y-3.5',
              isSelected
                ? 'ring-2 ring-accent bg-accent/10 border-accent'
                : 'bg-card/70 border-border/70 hover:border-accent/50',
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-[11px] font-mono font-bold">
                Scene {sc.index}: {sc.id}
              </span>
              <span className="text-[11px] font-mono text-muted-foreground">
                {loc?.canonical_name || sc.location_id} · {sc.time_of_day}
              </span>
            </div>
            <h4 className="text-sm font-bold text-foreground">
              {sc.heading || `${loc?.canonical_name || sc.location_id}`}
            </h4>
            <p className="text-xs text-muted-foreground leading-relaxed">{sc.summary}</p>

            <div className="space-y-2 pt-2.5 border-t border-border/50">
              <span className="text-[10px] font-bold uppercase text-muted-foreground">
                Dialogue Lines ({scDialogues.length})
              </span>
              {scDialogues.map((dl: StoryGraphDialogueLine) => {
                const speaker = entityMap[dl.speaker_id]
                return (
                  <div
                    key={dl.id}
                    className="p-3 rounded-lg bg-muted/40 border border-border/60 space-y-1"
                  >
                    <div className="flex items-center justify-between text-[10px] font-mono">
                      <span className="font-bold text-accent-dark uppercase">
                        {speaker?.canonical_name || dl.speaker_id}
                      </span>
                      <span className="text-muted-foreground">
                        {dl.delivery} · {dl.language}
                      </span>
                    </div>
                    <p className="text-xs italic text-foreground">"{dl.text}"</p>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  </div>
)

export { StepVisualReferenceSheetsSection } from './StudioStepReferenceImages'

