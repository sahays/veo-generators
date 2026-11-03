import { useCallback, useMemo, useState } from 'react'
import { Box, Loader2, Play } from 'lucide-react'
import { Button } from '@/components/Common'
import { Disclosure } from '@/components/ui/disclosure'
import { Skeleton } from '@/components/ui/skeleton'
import { isPrevizActive, usePrevizBoard, type PrevizBoardState } from '@/hooks/usePrevizBoard'
import type { PrevizRestyleVariant, PrevizRunPayload, ShotPreviz } from '@/types/previz'
import { groupShotsByScene, type PrevizSceneGroup, type SceneRef } from './previzLogic'
import { PrevizPromoteDialog, PrevizRunDialog, type PromoteTarget } from './PrevizDialogs'
import { PrevizHeader, PrevizLayoutsStrip } from './PrevizHeader'
import { PrevizShotCard } from './PrevizShotCard'

export interface PrevizBoardPanelProps {
  productionId: string
  scenes: SceneRef[]
  canWrite: boolean
}

const DEFAULT_RUN: PrevizRunPayload = { variant: 'previz_only', scene_ids: null, force: false }

const BoardSkeleton = () => (
  <div className="space-y-3" aria-busy="true" aria-label="Loading previz">
    <div className="flex gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="aspect-video w-36 rounded-lg" />)}</div>
    {[0, 1].map((i) => <Skeleton key={i} className="h-48 w-full rounded-xl" />)}
  </div>
)

const EmptyState = ({ canWrite, disabled, onRun }: { canWrite: boolean; disabled: boolean; onRun: () => void }) => (
  <div className="space-y-3 rounded-xl border border-dashed border-border p-6 text-center">
    <Box size={24} className="mx-auto text-muted-foreground" aria-hidden />
    <p className="text-xs text-muted-foreground">No previz yet. Render a Blender greybox of every shot to check blocking, framing and timing before spending on video.</p>
    {canWrite && <Button size="sm" icon={disabled ? Loader2 : Play} disabled={disabled} onClick={onRun}>Run previz</Button>}
  </div>
)

const groupSummary = (g: PrevizSceneGroup): string => {
  const done = g.shots.filter((s) => s.status === 'done').length
  const failed = g.shots.filter((s) => s.status === 'failed').length
  return `${done}/${g.shots.length} done${failed > 0 ? ` · ${failed} failed` : ''}`
}

interface SceneListProps {
  groups: PrevizSceneGroup[]
  state: PrevizBoardState
  canWrite: boolean
  onPromote: (shot: ShotPreviz, kind: PrevizRestyleVariant) => void
}

const SceneList = ({ groups, state, canWrite, onPromote }: SceneListProps) => (
  <div className="space-y-2">
    {groups.map((g, i) => (
      <Disclosure
        key={g.sceneId} defaultOpen={i === 0}
        title={<span className="text-sm font-medium text-foreground">{g.label}</span>}
        summary={<span className="text-[11px] tabular-nums text-muted-foreground">{groupSummary(g)}</span>}
        className="rounded-xl bg-card/50 px-3 ring-1 ring-border/50" triggerClassName="py-2.5" contentClassName="space-y-3 pb-3"
      >
        {g.shots.map((shot) => (
          <PrevizShotCard key={shot.shot_id} shot={shot} canWrite={canWrite} isBusy={state.pendingPromote !== null} pendingPromote={state.pendingPromote} onPromote={onPromote} />
        ))}
      </Disclosure>
    ))}
  </div>
)

function useConfirmFlows(state: PrevizBoardState) {
  const [runPayload, setRunPayload] = useState<PrevizRunPayload | null>(null)
  const [promoteTarget, setPromoteTarget] = useState<PromoteTarget | null>(null)
  const { clearActionError, run, promote } = state
  const requestRun = useCallback((p: PrevizRunPayload) => { clearActionError(); setRunPayload(p) }, [clearActionError])
  const requestPromote = useCallback((shot: ShotPreviz, variant: PrevizRestyleVariant) => { clearActionError(); setPromoteTarget({ shotId: shot.shot_id, variant }) }, [clearActionError])
  const confirmRun = useCallback(async () => { if (runPayload && (await run(runPayload))) setRunPayload(null) }, [runPayload, run])
  const confirmPromote = useCallback(async () => {
    if (promoteTarget && (await promote(promoteTarget.shotId, promoteTarget.variant))) setPromoteTarget(null)
  }, [promoteTarget, promote])
  return { runPayload, setRunPayload, promoteTarget, setPromoteTarget, requestRun, requestPromote, confirmRun, confirmPromote }
}

/** Studio step workspace for the Blender previz pipeline (lazy-loaded only when the step is expanded). */
export const PrevizBoardPanel = ({ productionId, scenes, canWrite }: PrevizBoardPanelProps) => {
  const state = usePrevizBoard(productionId)
  const flows = useConfirmFlows(state)
  const groups = useMemo(() => groupShotsByScene(state.board?.shots ?? [], scenes), [state.board, scenes])
  const isActive = isPrevizActive(state.board)
  const isFirstLoad = state.isLoading && !state.board
  return (
    <section className="space-y-4 rounded-2xl border border-border/70 bg-card/40 p-4">
      <PrevizHeader board={state.board} scenes={scenes} canWrite={canWrite} isActive={isActive} isStarting={state.isStarting} onRequestRun={flows.requestRun} />
      {isFirstLoad && <BoardSkeleton />}
      {state.loadError && !state.board && <p role="alert" className="text-xs text-red-500">{state.loadError}</p>}
      {state.board && state.board.layouts.length > 0 && <PrevizLayoutsStrip layouts={state.board.layouts} />}
      {state.board && groups.length === 0 && <EmptyState canWrite={canWrite} disabled={isActive || state.isStarting} onRun={() => flows.requestRun(DEFAULT_RUN)} />}
      {groups.length > 0 && <SceneList groups={groups} state={state} canWrite={canWrite} onPromote={flows.requestPromote} />}
      <PrevizRunDialog payload={flows.runPayload} isSubmitting={state.isStarting} error={state.actionError} onConfirm={() => void flows.confirmRun()} onCancel={() => flows.setRunPayload(null)} />
      <PrevizPromoteDialog target={flows.promoteTarget} isSubmitting={state.pendingPromote !== null} error={state.actionError} onConfirm={() => void flows.confirmPromote()} onCancel={() => flows.setPromoteTarget(null)} />
    </section>
  )
}
