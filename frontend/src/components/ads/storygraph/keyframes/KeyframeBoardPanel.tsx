import { useCallback, useMemo, useState } from 'react'
import { Film, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { KeyframeStripResponse } from '@/types/keyframes'
import type { StoryGraphStageRun } from '@/types/project'
import { KEYFRAMES_STAGE } from '../cascade/pipelineStages'
import { buildSuccessorIndex, keyframeRefreshKey } from './keyframeSummary'
import { KeyframeRegenDialog, type RegenMode, type RegenTarget } from './KeyframeRegenDialog'
import { KeyframeStripCard } from './KeyframeStripCard'
import { useKeyframeBoard, type KeyframeBoardState } from '@/hooks/useKeyframeBoard'

export interface KeyframeBoardPanelProps {
  productionId: string
  stageRuns: StoryGraphStageRun[]
  pipelineStatus?: string
  canWrite: boolean
  /** A stage run / pipeline is in flight: disable all mutating actions. */
  isBusy: boolean
  /** Opens the S8_KEYFRAMES cascade confirmation (force run → render → QA → assemble). */
  onRunKeyframes: () => void
}

const PanelHeader = ({ hasStrips, canWrite, isBusy, onRunKeyframes }: { hasStrips: boolean; canWrite: boolean; isBusy: boolean; onRunKeyframes: () => void }) => (
  <div className="flex flex-wrap items-center justify-between gap-2">
    <div>
      <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><Film size={14} />1 fps Keyframes ({KEYFRAMES_STAGE})</p>
      <p className="text-xs text-muted-foreground">Each clip is conditioned on its keyframe strip; frame t0 is shared with the previous clip&apos;s last frame.</p>
    </div>
    {canWrite && hasStrips && (
      <Button variant="outline" size="xs" icon={isBusy ? Loader2 : RefreshCw} disabled={isBusy} onClick={onRunKeyframes}>Regenerate all keyframes</Button>
    )}
  </div>
)

const EmptyState = ({ canWrite, isBusy, onRunKeyframes }: { canWrite: boolean; isBusy: boolean; onRunKeyframes: () => void }) => (
  <div className="space-y-3 rounded-xl border border-dashed border-border p-6 text-center">
    <Film size={24} className="mx-auto text-muted-foreground" />
    <p className="text-xs text-muted-foreground">No keyframes yet. Run the Keyframe Director to derive 1 fps strips for every clip before rendering.</p>
    {canWrite && <Button size="xs" icon={isBusy ? Loader2 : Film} disabled={isBusy} onClick={onRunKeyframes}>Generate keyframes ({KEYFRAMES_STAGE})</Button>}
  </div>
)

function useRegenFlow(state: KeyframeBoardState) {
  const [target, setTarget] = useState<RegenTarget | null>(null)
  const open = useCallback((strip: KeyframeStripResponse, t: number, mode: RegenMode) => setTarget({ strip, t, mode }), [])
  const close = useCallback(() => setTarget(null), [])
  const confirm = useCallback(async (instruction?: string) => {
    if (!target) return
    if (await state.regenerate(target.strip.shot_id, target.t, instruction)) setTarget(null)
  }, [target, state])
  return { target, open, close, confirm }
}

const BoardBody = ({ state, canWrite, isBusy, onRunKeyframes, onAction }: { state: KeyframeBoardState; canWrite: boolean; isBusy: boolean; onRunKeyframes: () => void; onAction: (s: KeyframeStripResponse, t: number, m: RegenMode) => void }) => {
  const strips = state.board?.shots.filter((s) => s.frames.length > 0 || s.set_id !== null) ?? []
  if (state.isLoading && !state.board) return <Skeleton className="h-24 w-full" />
  if (state.loadError) return <p className="text-xs text-red-400">{state.loadError}</p>
  if (strips.length === 0) return <EmptyState canWrite={canWrite} isBusy={isBusy} onRunKeyframes={onRunKeyframes} />
  return (
    <div className="space-y-3">
      {strips.map((strip) => (
        <KeyframeStripCard key={strip.shot_id} strip={strip} canWrite={canWrite} isBusy={isBusy} pending={state.pending} onAction={onAction} />
      ))}
    </div>
  )
}

/** Production-page board of per-shot S8_KEYFRAMES strips with per-frame regenerate / edit. */
export const KeyframeBoardPanel = ({ productionId, stageRuns, pipelineStatus, canWrite, isBusy, onRunKeyframes }: KeyframeBoardPanelProps) => {
  const state = useKeyframeBoard(productionId, keyframeRefreshKey(stageRuns, pipelineStatus))
  const flow = useRegenFlow(state)
  const successors = useMemo(() => buildSuccessorIndex(state.board?.shots ?? []), [state.board])
  const hasStrips = (state.board?.shots ?? []).some((s) => s.frames.length > 0)
  return (
    <section className="space-y-3 rounded-2xl border border-border/70 bg-card/40 p-4">
      <PanelHeader hasStrips={hasStrips} canWrite={canWrite} isBusy={isBusy} onRunKeyframes={onRunKeyframes} />
      <BoardBody state={state} canWrite={canWrite} isBusy={isBusy} onRunKeyframes={onRunKeyframes} onAction={flow.open} />
      <KeyframeRegenDialog
        target={flow.target}
        nextShotId={flow.target ? successors[flow.target.strip.shot_id] ?? null : null}
        isSubmitting={state.pending !== null}
        error={state.regenError}
        onConfirm={(instruction) => void flow.confirm(instruction)}
        onCancel={flow.close}
      />
    </section>
  )
}
