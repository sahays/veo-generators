import { Loader2 } from 'lucide-react'
import type { StoryGraphInteractionStep, StoryGraphScene } from '@/types/project'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'
import { useLazyDetail } from './useLazyDetail'

const StepRow = ({ st }: { st: StoryGraphInteractionStep }) => (
  <div className="p-2 rounded bg-muted/40 border border-border/60 text-[10px] font-mono space-y-0.5">
    <div className="font-bold text-foreground">
      #{st.step_index} {st.actor_id} → {st.action_verb} → {st.target_id || st.target_kind}
    </div>
    <div className="text-muted-foreground">{st.description}</div>
  </div>
)

/** Scene interaction steps, lazy-loaded (the lean snapshot ships only their count). */
export const SceneStepsPanel = ({ productionId, scene }: { productionId: string; scene: StoryGraphScene }) => {
  const { projects } = useAdsProjectActions()
  const preloaded = scene.interaction_steps
  const count = scene.interaction_step_count ?? preloaded?.length ?? 0
  const detail = useLazyDetail<StoryGraphScene>(
    preloaded || count === 0 ? null : `${productionId}/${scene.id}`,
    () => projects.getSceneDetail(productionId, scene.id),
  )
  const steps = preloaded || detail.data?.interaction_steps || []
  if (count === 0) return null
  return (
    <div className="space-y-1 pt-1">
      <span className="text-[10px] font-mono font-bold uppercase text-accent-dark block">
        Algorithmic Interaction Steps (1 Action / Step)
      </span>
      {detail.loading && (
        <p className="flex items-center gap-2 text-[11px] text-muted-foreground"><Loader2 size={12} className="animate-spin" /> Loading {count} steps…</p>
      )}
      {detail.error && <p className="text-[11px] text-red-400">{detail.error}</p>}
      {steps.map((st) => <StepRow key={st.step_index} st={st} />)}
    </div>
  )
}
