import { Box, ImageOff } from 'lucide-react'
import type { PrevizBoardResponse, PrevizLayout, PrevizRunPayload } from '@/types/previz'
import { STAGE_STATUS_META, type SceneRef } from './previzLogic'
import { FailureBanner, ToneBadge } from './PrevizMedia'
import { PrevizRunControls } from './PrevizRunControls'

export interface PrevizHeaderProps {
  board: PrevizBoardResponse | null
  scenes: SceneRef[]
  canWrite: boolean
  isActive: boolean
  isStarting: boolean
  onRequestRun: (payload: PrevizRunPayload) => void
}

const formatTime = (iso: string | null): string | null => (iso ? new Date(iso).toLocaleString() : null)

function runTimingText(board: PrevizBoardResponse | null): string | null {
  const run = board?.stage_run
  if (!run) return null
  const finished = formatTime(run.finished_at)
  if (finished) return `Finished ${finished}`
  const started = formatTime(run.started_at)
  return started ? `Started ${started}` : null
}

/** What previz is, Blender version, stage-run status and the Run control. */
export const PrevizHeader = ({ board, scenes, canWrite, isActive, isStarting, onRequestRun }: PrevizHeaderProps) => {
  const run = board?.stage_run ?? null
  const meta = STAGE_STATUS_META[run?.status ?? 'idle']
  const timing = runTimingText(board)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><Box size={14} aria-hidden />Blender Previz</p>
          <p className="text-xs text-muted-foreground">Greybox 3D blocking of every shot rendered in Blender, optionally restyled into final-look video.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span className="tabular-nums">Blender {board?.blender_version ?? '—'}</span>
          {timing && <span>· {timing}</span>}
          <ToneBadge tone={meta.tone} label={meta.label} />
        </div>
      </div>
      {run?.status === 'failed' && <FailureBanner reason={run.error} />}
      {canWrite && <PrevizRunControls scenes={scenes} disabled={isActive || isStarting} isRunning={isActive} onRequestRun={onRequestRun} />}
    </div>
  )
}

const LayoutThumb = ({ layout }: { layout: PrevizLayout }) => (
  <figure className="w-36 shrink-0 space-y-1">
    <div className="aspect-video overflow-hidden rounded-lg bg-muted ring-1 ring-border/60">
      {layout.thumbnail_url ? (
        <img src={layout.thumbnail_url} alt={`${layout.name} layout`} loading="lazy" decoding="async" className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-muted-foreground"><ImageOff size={16} aria-hidden /></div>
      )}
    </div>
    <figcaption className="flex items-center justify-between gap-1 text-[11px]">
      <span className="truncate text-foreground">{layout.name}</span>
      <span className="shrink-0 tabular-nums text-muted-foreground">v{layout.version}</span>
    </figcaption>
  </figure>
)

/** One thumbnail per location layout (the Blender set each scene is staged in). */
export const PrevizLayoutsStrip = ({ layouts }: { layouts: PrevizLayout[] }) => (
  <div className="space-y-1.5">
    <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Location layouts</p>
    <div className="flex gap-3 overflow-x-auto pb-1 scrollbar-thin">
      {layouts.map((l) => <LayoutThumb key={l.location_id} layout={l} />)}
    </div>
  </div>
)
