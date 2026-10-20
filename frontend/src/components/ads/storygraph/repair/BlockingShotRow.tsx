import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Disclosure } from '@/components/ui/disclosure'
import type { BlockingShot } from '@/types/storygraph'
import { ShotClipEditor } from './ShotClipEditor'
import { attemptsLabel, conciseReasons, deriveShotChip } from './shotRepairStatus'

export interface BlockingShotRowProps {
  shot: BlockingShot
  canWrite: boolean
  isBulkRepairing: boolean
  regeneratingShotId: string | null
  isBusy: boolean
  issues: string[]
  onSaveAndRegenerate: (shotId: string, omniPrompt: string) => Promise<boolean>
  onCancelEdit: (shotId: string) => void
}

const ShotReasons = ({ shot }: { shot: BlockingShot }) => {
  const { visible, hidden } = conciseReasons(shot)
  if (visible.length === 0) return null
  return (
    <p className="text-[11px] text-muted-foreground">
      {visible.join(' · ')}
      {hidden > 0 && <span className="opacity-70"> · +{hidden} more</span>}
    </p>
  )
}

/** One blocking shot: status chip, repair attempts, reasons and (when flagged) an inline editor. */
export const BlockingShotRow = (props: BlockingShotRowProps) => {
  const { shot, canWrite, isBulkRepairing, regeneratingShotId, isBusy, issues } = props
  const [editing, setEditing] = useState(false)
  const chip = deriveShotChip(shot, isBulkRepairing, regeneratingShotId)
  const cancel = () => { setEditing(false); props.onCancelEdit(shot.shot_id) }
  const save = async (prompt: string) => {
    if (await props.onSaveAndRegenerate(shot.shot_id, prompt)) setEditing(false)
  }
  return (
    <li className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-mono font-bold text-foreground">{shot.shot_id}</span>
        <Badge variant={chip.variant}>{chip.label}</Badge>
        <span className="text-[10px] font-mono text-muted-foreground">{attemptsLabel(shot)}</span>
      </div>
      <ShotReasons shot={shot} />
      {shot.needs_manual_edit && canWrite && (
        <Disclosure open={editing} onOpenChange={(o) => (o ? setEditing(true) : cancel())} title={<span className="text-xs font-semibold text-amber-300">Edit &amp; regenerate</span>} contentClassName="pt-2">
          <ShotClipEditor
            shot={shot} issues={issues} isSaving={regeneratingShotId === shot.shot_id}
            disabled={isBusy || isBulkRepairing || regeneratingShotId !== null} onSave={(p) => void save(p)} onCancel={cancel}
          />
        </Disclosure>
      )}
    </li>
  )
}
