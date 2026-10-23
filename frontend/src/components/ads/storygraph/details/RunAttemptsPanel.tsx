import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ShotRunHistory, StoryGraphGenerationRun } from '@/types/project'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import { useLazyDetail } from './useLazyDetail'

const AttemptRow = ({ run, isActive, isSelected }: { run: StoryGraphGenerationRun; isActive: boolean; isSelected: boolean }) => (
  <div
    className={cn(
      'flex items-center justify-between gap-2 p-2 rounded border text-[10px] font-mono',
      isSelected ? 'border-accent bg-accent/10' : 'border-border/60 bg-muted/30',
    )}
  >
    <span className="text-foreground">Attempt #{run.attempt}{isActive ? ' · active' : ''}</span>
    <span className={run.status === 'approved' ? 'text-emerald-400' : 'text-amber-400'}>{run.status}</span>
  </div>
)

/** Lazily loads every render attempt of a shot plus the selected run's compiled prompt. */
export const RunAttemptsPanel = ({ productionId, shotId, runId }: { productionId: string; shotId: string; runId: string }) => {
  const { projects } = useAdsProjectActions()
  const history = useLazyDetail<ShotRunHistory>(`${productionId}/${shotId}`, () => projects.getShotRuns(productionId, shotId))
  if (history.loading && !history.data) {
    return <p className="flex items-center gap-2 text-[11px] text-muted-foreground"><Loader2 size={12} className="animate-spin" /> Loading attempts…</p>
  }
  if (history.error) return <p className="text-[11px] text-red-400">{history.error}</p>
  const runs = history.data?.runs || []
  const selected = runs.find((r) => r.id === runId)
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Compiled Shot Prompt</span>
        <pre className="p-2.5 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-48 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
          {selected?.compiled_prompt || 'Prompt unavailable for this attempt.'}
        </pre>
      </div>
      <div className="space-y-1">
        <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">Run Attempts ({runs.length})</span>
        {runs.map((r) => (
          <AttemptRow key={r.id} run={r} isActive={r.id === history.data?.active_run_id} isSelected={r.id === runId} />
        ))}
      </div>
    </div>
  )
}
