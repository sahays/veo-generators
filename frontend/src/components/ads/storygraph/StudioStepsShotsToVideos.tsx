import {
  CheckCircle2,
  Music,
  ShieldCheck,
  Terminal,
  RefreshCw,
  Loader2,
  AlertTriangle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import type {
  StoryGraphAuditEntry,
  StoryGraphBeat,
  StoryGraphChangeRequest,
  StoryGraphDialogueLine,
  StoryGraphMusicCue,
  StoryGraphScene,
  StoryGraphShot,
  StoryGraphValidationIssue,
} from '@/types/project'
import type { SelectedInspectorItem } from './storyGraphStudioTypes'
import { ShotLookPanel } from './ShotLookPanel'
import { AuditLogCard } from './details/AuditLogCard'

export const StepShotBreakdownSection = ({
  shots,
  dialogueLines,
  musicCues,
  scenes,
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
  selectedItem,
  onSelectItem,
}: {
  shots: StoryGraphShot[]
  dialogueLines: StoryGraphDialogueLine[]
  musicCues: StoryGraphMusicCue[]
  scenes?: StoryGraphScene[]
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string) => void
  selectedItem: SelectedInspectorItem | null
  onSelectItem: (item: SelectedInspectorItem) => void
}) => (
  <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Click any shot card to inspect its timed ActionBeats, cast appearances, and compiled
          Jinja2 prompt in the details drawer.
        </p>
      </div>
      {canWrite && (
        <div className="flex items-center gap-2">
          <Button
            size="xs"
            variant="outline"
            icon={busyAction === 'S4_SHOTS' ? Loader2 : RefreshCw}
            onClick={() => onRunStage('S4_SHOTS')}
            disabled={!!busyAction || isRunningPipeline}
          >
            Regenerate Shots (S4)
          </Button>
          <Button
            size="xs"
            variant="outline"
            icon={busyAction === 'S5_MUSIC' ? Loader2 : RefreshCw}
            onClick={() => onRunStage('S5_MUSIC')}
            disabled={!!busyAction || isRunningPipeline}
          >
            Regenerate Music (S5)
          </Button>
        </div>
      )}
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
      {shots.map((sh: StoryGraphShot) => {
        const shotDialogues = dialogueLines.filter(
          (dl) => (sh.dialogue_ids || []).includes(dl.id) || dl.shot_id === sh.id,
        )
        const cue = musicCues.find((m) => m.id === sh.music_cue_id)
        const isSelected = selectedItem?.kind === 'shot' && selectedItem?.id === sh.id
        return (
          <div
            key={sh.id}
            onClick={() =>
              onSelectItem({
                kind: 'shot',
                id: sh.id,
                data: { shot: sh, dialogues: shotDialogues, cue },
              })
            }
            className={cn(
              'cursor-pointer rounded-2xl p-5 border transition-all space-y-3.5',
              isSelected
                ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg'
                : 'bg-card/80 border-border/70 hover:border-accent/50',
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                  {sh.id}
                </span>
                <span className="text-xs font-mono text-muted-foreground">
                  #{sh.story_order} · {sh.duration_s}s · {sh.camera?.shot_size} ·{' '}
                  {sh.camera?.lens_mm}mm
                </span>
              </div>
              {sh.continue_from_last_frame && (
                <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 text-[10px] font-mono">
                  Frame Continuity
                </span>
              )}
            </div>

            <ShotLookPanel shot={sh} scenes={scenes} />

            <div className="space-y-2 text-xs">
              {(sh.beats || []).map((b: StoryGraphBeat, idx: number) => (
                <div
                  key={idx}
                  className="p-2.5 rounded-lg bg-muted/40 border border-border/50 leading-relaxed"
                >
                  <span className="font-mono text-accent-dark mr-1.5">
                    ({b.t_start_s.toFixed(1)}–{b.t_end_s.toFixed(1)}s)
                  </span>
                  <span>{b.description}</span>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-border/40 text-[11px] font-mono text-muted-foreground">
              <span>
                {(sh.cast || []).length} Cast · {shotDialogues.length} Dialogue Lines
              </span>
              {cue && (
                <span className="flex items-center gap-1 text-accent-dark">
                  <Music size={12} /> {cue.mood}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  </div>
)

export const StepValidatorCompilerSection = ({
  productionId,
  validationIssues,
  changeRequests,
  auditLog,
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
}: {
  productionId: string
  validationIssues: StoryGraphValidationIssue[]
  changeRequests: StoryGraphChangeRequest[]
  auditLog: StoryGraphAuditEntry[]
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string) => void
}) => (
  <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
      </div>
      {canWrite && (
        <div className="flex items-center gap-2">
          <Button
            size="xs"
            variant="outline"
            icon={busyAction === 'S6_VALIDATE' ? Loader2 : ShieldCheck}
            onClick={() => onRunStage('S6_VALIDATE')}
            disabled={!!busyAction || isRunningPipeline}
          >
            Run Validator (S6)
          </Button>
          <Button
            size="xs"
            variant="outline"
            icon={busyAction === 'S7_COMPILE' ? Loader2 : Terminal}
            onClick={() => onRunStage('S7_COMPILE')}
            disabled={!!busyAction || isRunningPipeline}
          >
            Compile All Prompts (S7)
          </Button>
        </div>
      )}
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <Card
        title={`Continuity Invariants V1–V13 (${validationIssues.length} Issues)`}
        icon={ShieldCheck}
      >
        {validationIssues.length === 0 ? (
          <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs text-emerald-400 flex items-center gap-2">
            <CheckCircle2 size={16} />
            All V1–V13 continuity, state, asset approval, and speech-rate invariants passed!
          </div>
        ) : (
          <div className="space-y-2">
            {validationIssues.map((iss, idx) => (
              <div
                key={idx}
                className={cn(
                  'p-3 rounded-lg border text-xs flex items-start gap-2',
                  iss.severity === 'error'
                    ? 'bg-red-500/10 border-red-500/30 text-red-300'
                    : 'bg-amber-500/10 border-amber-500/30 text-amber-300',
                )}
              >
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <div>
                  <span className="font-mono font-bold mr-2">
                    [{iss.code}] ({iss.node_id})
                  </span>
                  <span>{iss.message}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {changeRequests.length > 0 && (
          <div className="mt-4 pt-4 border-t border-border/50 space-y-2">
            <h5 className="text-xs font-bold uppercase text-muted-foreground">
              Cross-Role ChangeRequests ({changeRequests.length})
            </h5>
            {changeRequests.map((cr: StoryGraphChangeRequest) => (
              <div key={cr.id} className="p-3 rounded bg-muted/40 border border-border text-xs">
                <span className="font-mono font-bold text-accent-dark">
                  {cr.from_role} → {cr.to_role} ({cr.target_node_id}):
                </span>{' '}
                {cr.reason}
              </div>
            ))}
          </div>
        )}
      </Card>

      <AuditLogCard productionId={productionId} recent={auditLog} />
    </div>
  </div>
)

export { StepVideoRendersSection } from './StudioStepVideoRenders'

