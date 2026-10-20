import { AlertTriangle, CheckCircle2, Film, Loader2, Scissors, Wrench } from 'lucide-react'
import { Button } from '@/components/Common'
import { Disclosure } from '@/components/ui/disclosure'
import type { Project, StoryGraphGenerationRun } from '@/types/project'
import { MAX_SHOT_REPAIR_ATTEMPTS, type BlockingShot, type ShotRepairReport } from '@/types/storygraph'
import { useAssemblyReadiness } from './useAssemblyReadiness'
import { BlockingShotRow } from './repair/BlockingShotRow'
import { autoRepairableShotIds } from './repair/shotRepairStatus'
import { useShotRepair, type ShotRepairState } from './repair/useShotRepair'

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

const PartialAssemblyNotice = () => (
  <div className="flex items-start gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 p-3 text-xs text-sky-300">
    <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
    <span>Partial cut: the master was stitched from approved shots only. Unapproved shots were skipped.</span>
  </div>
)

const RepairReportSummary = ({ report }: { report: ShotRepairReport }) => {
  const approved = report.approved.length
  const flagged = report.flagged.length
  return (
    <p className="text-xs text-foreground/80">
      Repair finished: {approved} approved{flagged > 0 ? `, ${flagged} flagged for your edit` : ''} · {report.total_renders} render(s) used.
    </p>
  )
}

interface FinalCutReadyProps { canWrite: boolean; isBusy: boolean; onStitchFinalCut: () => void }

const FinalCutReady = ({ canWrite, isBusy, onStitchFinalCut }: FinalCutReadyProps) => (
  <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4">
    <div className="flex items-center gap-2 text-sm font-semibold text-emerald-300">
      <CheckCircle2 size={16} /> Every shot passed QA.
    </div>
    {canWrite && (
      <Button variant="primary" size="xs" icon={Film} disabled={isBusy} onClick={onStitchFinalCut}>
        All shots approved — Stitch final cut
      </Button>
    )}
  </div>
)

interface RepairActionsProps {
  repairable: string[]
  readyCount: number
  isAssembling: boolean
  isBusy: boolean
  repair: ShotRepairState
  onStitchApproved: () => void
}

const RepairActions = ({ repairable, readyCount, isAssembling, isBusy, repair, onStitchApproved }: RepairActionsProps) => {
  const locked = isBusy || isAssembling || repair.isRepairing || repair.regeneratingShotId !== null
  return (
    <div className="flex flex-wrap items-center gap-2">
      {repairable.length > 0 && (
        <Button variant="primary" size="xs" icon={repair.isRepairing ? Loader2 : Wrench} disabled={locked} onClick={() => void repair.repairFailed(repairable)}>
          {repair.isRepairing ? `Repairing ${plural(repairable.length, 'shot')}…` : `Repair ${plural(repairable.length, 'failed shot')}`}
        </Button>
      )}
      <Button variant="outline" size="xs" icon={isAssembling ? Loader2 : Scissors} disabled={readyCount === 0 || locked} onClick={onStitchApproved}>
        Stitch approved shots only
      </Button>
    </div>
  )
}

interface BlockingListProps {
  blocking: BlockingShot[]
  canWrite: boolean
  isBusy: boolean
  repair: ShotRepairState
}

const BlockingList = ({ blocking, canWrite, isBusy, repair }: BlockingListProps) => (
  <Disclosure title={<span className="text-xs text-amber-300">Show {plural(blocking.length, 'blocking shot')}</span>} contentClassName="pt-2">
    <ul className="space-y-2">
      {blocking.map((shot) => (
        <BlockingShotRow
          key={shot.shot_id} shot={shot} canWrite={canWrite} isBusy={isBusy} isBulkRepairing={repair.isRepairing}
          regeneratingShotId={repair.regeneratingShotId} issues={repair.editIssues[shot.shot_id] ?? []}
          onSaveAndRegenerate={repair.saveAndRegenerate} onCancelEdit={repair.clearEditIssues}
        />
      ))}
    </ul>
  </Disclosure>
)

interface AssemblyReadinessPanelProps {
  productionId: string
  pipelineStatus?: string
  activeGenerationRuns: StoryGraphGenerationRun[]
  canWrite: boolean
  isBusy: boolean
  onGraphUpdated: (snapshot: Project) => void
  /** Existing S10 stage action (strict final-cut assembly). */
  onStitchFinalCut: () => void
}

interface AttentionCardProps {
  blocking: BlockingShot[]
  readyCount: number
  canWrite: boolean
  isBusy: boolean
  isAssembling: boolean
  error: string | null
  repair: ShotRepairState
  onStitchApproved: () => void
}

const AttentionCard = ({ blocking, readyCount, canWrite, isBusy, isAssembling, error, repair, onStitchApproved }: AttentionCardProps) => (
  <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
        <AlertTriangle size={16} />
        {plural(blocking.length, 'shot')} need{blocking.length === 1 ? 's' : ''} attention · {readyCount} ready
      </div>
      {canWrite && (
        <RepairActions repairable={autoRepairableShotIds(blocking)} readyCount={readyCount} isAssembling={isAssembling} isBusy={isBusy} repair={repair} onStitchApproved={onStitchApproved} />
      )}
    </div>
    <p className="text-[11px] text-muted-foreground">
      Each failing shot gets up to {MAX_SHOT_REPAIR_ATTEMPTS} automatic repair attempts; shots still failing are flagged for your edit.
    </p>
    {repair.isRepairing && <p className="text-xs text-indigo-300">Repairing in the background — this can take several minutes. You can keep working.</p>}
    {repair.report && <RepairReportSummary report={repair.report} />}
    {blocking.length > 0 && <BlockingList blocking={blocking} canWrite={canWrite} isBusy={isBusy} repair={repair} />}
    {error && <p className="text-xs text-red-400">{error}</p>}
  </div>
)

/** S10 readiness: repair failed shots, edit flagged ones, or stitch approved shots only. */
export const AssemblyReadinessPanel = (props: AssemblyReadinessPanelProps) => {
  const { productionId, pipelineStatus, activeGenerationRuns, canWrite, isBusy, onGraphUpdated } = props
  const refreshKey = `${pipelineStatus ?? ''}|${activeGenerationRuns.map((r) => `${r.id}:${r.status}`).join(',')}`
  const { readiness, isAssembling, assembleError, assembleApprovedOnly, refresh } = useAssemblyReadiness(productionId, refreshKey, onGraphUpdated)
  const repair = useShotRepair(productionId, onGraphUpdated, refresh)
  const blocking = readiness?.blocking ?? []
  const readyCount = readiness?.ready_shots.length ?? 0
  const allReady = readiness !== null && blocking.length === 0 && readyCount > 0
  if (allReady && (pipelineStatus === 'needs_review' || repair.report)) {
    return <FinalCutReady canWrite={canWrite} isBusy={isBusy || isAssembling} onStitchFinalCut={props.onStitchFinalCut} />
  }
  const isPartial = pipelineStatus === 'completed_partial'
  if (pipelineStatus !== 'needs_review' && blocking.length === 0) return isPartial ? <PartialAssemblyNotice /> : null
  return (
    <div className="space-y-3">
      {isPartial && <PartialAssemblyNotice />}
      <AttentionCard
        blocking={blocking} readyCount={readyCount} canWrite={canWrite} isBusy={isBusy} isAssembling={isAssembling}
        error={assembleError || repair.repairError} repair={repair} onStitchApproved={() => void assembleApprovedOnly()}
      />
    </div>
  )
}
