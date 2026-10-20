import { useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/Common'
import { Textarea } from '@/components/ui/textarea'
import type { BlockingShot } from '@/types/storygraph'

interface ShotClipEditorProps {
  shot: BlockingShot
  issues: string[]
  isSaving: boolean
  disabled: boolean
  onSave: (omniPrompt: string) => void
  onCancel: () => void
}

const IssueList = ({ title, items, tone }: { title: string; items: string[]; tone: 'hint' | 'error' }) =>
  items.length === 0 ? null : (
    <div className={tone === 'error' ? 'text-[11px] text-red-400' : 'text-[11px] text-muted-foreground'}>
      <p className="font-semibold">{title}</p>
      <ul className="list-disc pl-4 space-y-0.5">{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  )

/** Inline editor for a flagged shot's clip omni prompt (PATCH clip → regenerate). */
export const ShotClipEditor = ({ shot, issues, isSaving, disabled, onSave, onCancel }: ShotClipEditorProps) => {
  const [prompt, setPrompt] = useState(shot.clip_omni_prompt ?? '')
  const trimmed = prompt.trim()
  return (
    <div className="space-y-2">
      <IssueList title="Why automatic repair gave up" items={shot.manual_edit_reasons} tone="hint" />
      <Textarea
        aria-label={`Clip prompt for ${shot.shot_id}`}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        disabled={isSaving}
        className="min-h-[140px] font-mono text-xs"
        error={issues.length > 0 ? 'Fix the issues below and try again.' : undefined}
      />
      <IssueList title="Validation issues" items={issues} tone="error" />
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="xs" onClick={onCancel} disabled={isSaving}>Cancel</Button>
        <Button variant="primary" size="xs" icon={isSaving ? Loader2 : RefreshCw} disabled={disabled || isSaving || trimmed.length === 0} onClick={() => onSave(trimmed)}>
          {isSaving ? 'Regenerating…' : 'Save & regenerate'}
        </Button>
      </div>
    </div>
  )
}
