import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { buildCascadePlan, KEYFRAMES_STAGE, type CascadeRequest, type CascadeStep } from './pipelineStages'

const RENDER_STAGE = 'S8_RENDER'

interface RegenerateCascadeDialogProps {
  request: CascadeRequest | null
  /** True when some shots failed QA, so targeted repair is the better option than a full re-render. */
  hasBlockingShots: boolean
  onConfirm: () => void
  onCancel: () => void
}

const DownstreamAgentList = ({ steps }: { steps: CascadeStep[] }) => (
  <div className="space-y-1.5">
    <p className="text-xs font-semibold text-foreground">Downstream agents that will re-run (unchanged ones are skipped):</p>
    <ol className="space-y-1">
      {steps.map((step) => (
        <li key={step.stageId} className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="px-1.5 py-0.5 rounded bg-muted text-[10px] font-mono font-bold text-foreground">{step.short}</span>
          <span>{step.label}</span>
          <span className="font-mono text-[10px] opacity-70">{step.stageId}</span>
          {step.serverRun && <span className="text-[10px] italic text-amber-300">cascaded by the server</span>}
        </li>
      ))}
    </ol>
  </div>
)

const CostWarning = () => (
  <div className="flex gap-2 p-3 rounded-xl border border-amber-500/40 bg-amber-500/10 text-xs text-amber-300">
    <AlertTriangle size={16} className="shrink-0 mt-0.5" />
    <p>
      Shots whose inputs change will be re-rendered with Veo, which costs time and money. Previously
      approved clips from the old version will not be reused for changed shots.
    </p>
  </div>
)

const KeyframeCascadeWarning = () => (
  <div className="flex gap-2 p-3 rounded-xl border border-amber-500/40 bg-amber-500/10 text-xs text-amber-300">
    <AlertTriangle size={16} className="shrink-0 mt-0.5" />
    <div className="space-y-1">
      <p className="font-semibold">Re-derives the 1 fps keyframe strip of every clip, then re-renders all clips downstream with Veo.</p>
      <p>Clips whose keyframes change lose their current render (approved or not). Manually edited strips are re-derived too.</p>
    </div>
  </div>
)

const RenderWipeWarning = ({ hasBlockingShots }: { hasBlockingShots: boolean }) => (
  <div className="flex gap-2 p-3 rounded-xl border border-red-500/40 bg-red-500/10 text-xs text-red-300">
    <AlertTriangle size={16} className="shrink-0 mt-0.5" />
    <div className="space-y-1">
      <p className="font-semibold">This deletes ALL existing clips — including approved ones — and re-renders every shot with Veo.</p>
      {hasBlockingShots && (
        <p>
          Only some shots failed QA. Cancel and use <span className="font-semibold">“Repair failed shots”</span> in the
          Videos step instead: it re-renders just the failing shots and keeps approved clips.
        </p>
      )}
    </div>
  </div>
)

interface DialogCopy {
  title: string
  subtitle?: string
  confirmLabel: string
}

function confirmLabelFor(head: CascadeStep, planLength: number): string {
  if (head.stageId === RENDER_STAGE) return 'Delete all clips & re-render'
  if (head.stageId === KEYFRAMES_STAGE) return 'Re-derive keyframes & re-render'
  return planLength > 1 ? `Regenerate ${planLength} agents` : 'Regenerate'
}

function buildDialogCopy(request: CascadeRequest | null, plan: CascadeStep[]): DialogCopy {
  const head = plan[0]
  if (!request || !head) return { title: 'Regenerate stage?', confirmLabel: 'Regenerate' }
  const hasDownstream = plan.length > 1
  const qualityNote = request.quality ? ` (${request.quality === 'final' ? '720p final' : '360p draft'})` : ''
  return {
    title: hasDownstream ? `Regenerate ${head.label} and all downstream agents?` : `Regenerate ${head.label}?`,
    subtitle: `${head.short} · ${head.stageId}${qualityNote} will be force re-run`,
    confirmLabel: confirmLabelFor(head, plan.length),
  }
}

/** Confirmation modal shown before regenerating a stage and its downstream agents. */
export const RegenerateCascadeDialog = ({ request, hasBlockingShots, onConfirm, onCancel }: RegenerateCascadeDialogProps) => {
  const plan = request ? buildCascadePlan(request) : []
  const downstream = plan.slice(1)
  const copy = buildDialogCopy(request, plan)
  const wipesClips = plan[0]?.stageId === RENDER_STAGE
  const rederivesKeyframes = plan[0]?.stageId === KEYFRAMES_STAGE
  return (
    <Modal
      isOpen={request !== null}
      onClose={onCancel}
      title={copy.title}
      subtitle={copy.subtitle}
      maxWidth="max-w-lg"
      footer={
        <>
          <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
          <Button variant={wipesClips ? 'destructive' : 'primary'} size="sm" icon={RefreshCw} onClick={onConfirm}>
            {copy.confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {wipesClips && <RenderWipeWarning hasBlockingShots={hasBlockingShots} />}
        {rederivesKeyframes && <KeyframeCascadeWarning />}
        {downstream.length > 0 && <DownstreamAgentList steps={downstream} />}
        {!wipesClips && !rederivesKeyframes && <CostWarning />}
      </div>
    </Modal>
  )
}
