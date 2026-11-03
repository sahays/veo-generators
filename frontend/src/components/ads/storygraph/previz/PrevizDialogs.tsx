import { AlertTriangle, Loader2, Play, Star } from 'lucide-react'
import { Button } from '@/components/Common'
import { Modal } from '@/components/ui/dialog'
import type { PrevizRestyleVariant, PrevizRunPayload } from '@/types/previz'
import { RUN_VARIANT_OPTIONS, VARIANT_LABEL, runCostLines } from './previzLogic'

export interface PromoteTarget {
  shotId: string
  variant: PrevizRestyleVariant
}

const NoteList = ({ lines }: { lines: string[] }) => (
  <div className="flex gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
    <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
    <ul className="list-disc space-y-1 pl-4">
      {lines.map((line) => <li key={line}>{line}</li>)}
    </ul>
  </div>
)

const DialogActions = ({ label, icon, isSubmitting, onConfirm, onCancel }: { label: string; icon: typeof Play; isSubmitting: boolean; onConfirm: () => void; onCancel: () => void }) => (
  <>
    <Button variant="outline" size="sm" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
    <Button size="sm" icon={isSubmitting ? Loader2 : icon} disabled={isSubmitting} onClick={onConfirm}>{label}</Button>
  </>
)

interface RunDialogProps {
  payload: PrevizRunPayload | null
  isSubmitting: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/** Cost confirmation before `POST /previz/run`. */
export const PrevizRunDialog = ({ payload, isSubmitting, error, onConfirm, onCancel }: RunDialogProps) => {
  const label = RUN_VARIANT_OPTIONS.find((o) => o.value === payload?.variant)?.label ?? ''
  const lines = payload ? runCostLines(payload.variant, payload.scene_ids?.length ?? null, payload.force) : []
  return (
    <Modal
      isOpen={payload !== null} onClose={onCancel} title={`Run Blender previz · ${label}`}
      subtitle="Runs in the background; this board refreshes while it works." maxWidth="max-w-lg"
      footer={<DialogActions label="Start run" icon={Play} isSubmitting={isSubmitting} onConfirm={onConfirm} onCancel={onCancel} />}
    >
      <div className="space-y-3">
        <NoteList lines={lines} />
        {error && <p role="alert" className="text-xs text-red-500">{error}</p>}
      </div>
    </Modal>
  )
}

interface PromoteDialogProps {
  target: PromoteTarget | null
  isSubmitting: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

/** Confirmation before `POST /previz/shots/{id}/promote`. */
export const PrevizPromoteDialog = ({ target, isSubmitting, error, onConfirm, onCancel }: PromoteDialogProps) => (
  <Modal
    isOpen={target !== null} onClose={onCancel} title={`Use ${target ? VARIANT_LABEL[target.variant] : ''} for ${target?.shotId ?? ''}?`}
    subtitle="Blender previz · promote render" maxWidth="max-w-lg"
    footer={<DialogActions label="Use this render" icon={Star} isSubmitting={isSubmitting} onConfirm={onConfirm} onCancel={onCancel} />}
  >
    <div className="space-y-3">
      <NoteList lines={[
        'Marks this render as the chosen take for this shot.',
        "Replaces the shot's current clip: S9 QA and S10 assembly will use this render.",
        'If another variant of this shot is currently in use, it is replaced.',
      ]} />
      {error && <p role="alert" className="text-xs text-red-500">{error}</p>}
    </div>
  </Modal>
)
