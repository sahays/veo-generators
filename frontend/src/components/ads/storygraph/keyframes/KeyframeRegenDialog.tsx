import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, PenLine, RefreshCw } from 'lucide-react'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { KEYFRAME_INSTRUCTION_MAX, type KeyframeStripResponse } from '@/types/keyframes'
import { regenerateImpact } from './keyframeSummary'

export type RegenMode = 'regenerate' | 'edit'

/** The frame a user asked to regenerate (or edit with an instruction). */
export interface RegenTarget {
  strip: KeyframeStripResponse
  t: number
  mode: RegenMode
}

interface KeyframeRegenDialogProps {
  target: RegenTarget | null
  nextShotId: string | null
  isSubmitting: boolean
  error: string | null
  onConfirm: (instruction?: string) => void
  onCancel: () => void
}

const ImpactList = ({ lines }: { lines: string[] }) => (
  <div className="flex gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-300">
    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
    <ul className="list-disc space-y-1 pl-4">
      {lines.map((line) => <li key={line}>{line}</li>)}
    </ul>
  </div>
)

const InstructionField = ({ value, disabled, onChange }: { value: string; disabled: boolean; onChange: (v: string) => void }) => (
  <Textarea
    label={`Instruction (${value.length}/${KEYFRAME_INSTRUCTION_MAX})`}
    placeholder="e.g. She should be holding the red umbrella in her left hand, facing the camera."
    value={value}
    maxLength={KEYFRAME_INSTRUCTION_MAX}
    onChange={(e) => onChange(e.target.value)}
    disabled={disabled}
  />
)

const DialogFooter = ({ isEdit, isSubmitting, canSubmit, onConfirm, onCancel }: { isEdit: boolean; isSubmitting: boolean; canSubmit: boolean; onConfirm: () => void; onCancel: () => void }) => (
  <>
    <Button variant="outline" size="sm" onClick={onCancel} disabled={isSubmitting}>Cancel</Button>
    <Button size="sm" icon={isSubmitting ? Loader2 : isEdit ? PenLine : RefreshCw} disabled={!canSubmit} onClick={onConfirm}>
      {isEdit ? 'Apply edit & re-derive' : 'Regenerate from here'}
    </Button>
  </>
)

/** Confirmation (and optional human instruction) before re-deriving frames t..N of one clip. */
export const KeyframeRegenDialog = ({ target, nextShotId, isSubmitting, error, onConfirm, onCancel }: KeyframeRegenDialogProps) => {
  const [instruction, setInstruction] = useState('')
  useEffect(() => { setInstruction('') }, [target])
  const isEdit = target?.mode === 'edit'
  const trimmed = instruction.trim()
  const shotLabel = target ? `${target.strip.shot_id} · t${target.t}` : ''
  const footer = (
    <DialogFooter isEdit={isEdit} isSubmitting={isSubmitting} canSubmit={!isSubmitting && (!isEdit || trimmed.length > 0)}
      onConfirm={() => onConfirm(isEdit ? trimmed : undefined)} onCancel={onCancel} />
  )
  return (
    <Modal isOpen={target !== null} onClose={onCancel} title={isEdit ? `Edit keyframe ${shotLabel}` : `Regenerate from ${shotLabel}?`}
      subtitle="S8_KEYFRAMES · new keyframe set version" maxWidth="max-w-lg" footer={footer}>
      <div className="space-y-4">
        {target && <ImpactList lines={regenerateImpact(target.strip, target.t, nextShotId)} />}
        {isEdit && <InstructionField value={instruction} disabled={isSubmitting} onChange={setInstruction} />}
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    </Modal>
  )
}
