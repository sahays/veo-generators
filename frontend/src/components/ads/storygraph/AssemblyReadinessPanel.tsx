import { AlertTriangle, CheckCircle2, Loader2, Scissors } from 'lucide-react'
import { Button } from '@/components/Common'
import { Disclosure } from '@/components/ui/disclosure'
import type { Project, StoryGraphGenerationRun } from '@/types/project'
import type { BlockingShot } from '@/types/storygraph'
import { useAssemblyReadiness } from './useAssemblyReadiness'

const TagList = ({ label, items }: { label: string; items: string[] }) =>
  items.length === 0 ? null : (
    <div className="text-[11px] text-muted-foreground">
      <span className="font-semibold text-foreground/80">{label}: </span>
      {items.join(' · ')}
    </div>
  )

const BlockingShotRow = ({ shot }: { shot: BlockingShot }) => (
  <li className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-1">
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-mono font-bold text-foreground">{shot.shot_id}</span>
      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-amber-500/20 text-amber-400">
        {shot.latest_status}
      </span>
    </div>
    <TagList label="Failure reasons" items={shot.failure_reasons} />
    <TagList label="Artifact flags" items={shot.artifact_flags} />
  </li>
)

const PartialAssemblyNotice = () => (
  <div className="flex items-start gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 p-3 text-xs text-sky-300">
    <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
    <span>Partial cut: the master was stitched from approved shots only. Unapproved shots were skipped.</span>
  </div>
)

interface AssemblyReadinessPanelProps {
  productionId: string
  pipelineStatus?: string
  activeGenerationRuns: StoryGraphGenerationRun[]
  canWrite: boolean
  isBusy: boolean
  onGraphUpdated: (snapshot: Project) => void
}

/** S10 readiness: lists shots blocking assembly and offers an approved-only stitch. */
export const AssemblyReadinessPanel = ({
  productionId, pipelineStatus, activeGenerationRuns, canWrite, isBusy, onGraphUpdated,
}: AssemblyReadinessPanelProps) => {
  const refreshKey = `${pipelineStatus ?? ''}|${activeGenerationRuns.map((r) => `${r.id}:${r.status}`).join(',')}`
  const { readiness, isAssembling, assembleError, assembleApprovedOnly } = useAssemblyReadiness(productionId, refreshKey, onGraphUpdated)
  const blocking = readiness?.blocking ?? []
  const readyCount = readiness?.ready_shots.length ?? 0
  const needsReview = pipelineStatus === 'needs_review' || blocking.length > 0
  if (!needsReview) return pipelineStatus === 'completed_partial' ? <PartialAssemblyNotice /> : null
  return (
    <div className="space-y-3">
      {pipelineStatus === 'completed_partial' && <PartialAssemblyNotice />}
      <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
            <AlertTriangle size={16} />
            {blocking.length} shot(s) not approved for assembly · {readyCount} ready
          </div>
          {canWrite && (
            <Button variant="primary" size="xs" icon={isAssembling ? Loader2 : Scissors} disabled={readyCount === 0 || isAssembling || isBusy} onClick={() => void assembleApprovedOnly()}>
              Stitch approved shots only
            </Button>
          )}
        </div>
        {blocking.length > 0 && (
          <Disclosure title={<span className="text-xs text-amber-300">Show {blocking.length} blocking shot(s)</span>} contentClassName="pt-2">
            <ul className="space-y-2">{blocking.map((shot) => <BlockingShotRow key={shot.shot_id} shot={shot} />)}</ul>
          </Disclosure>
        )}
        {assembleError && <p className="text-xs text-red-400">{assembleError}</p>}
      </div>
    </div>
  )
}
