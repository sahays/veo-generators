import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { Button } from '@/components/Common'
import { Checkbox } from '@/components/ui/checkbox'
import { Disclosure } from '@/components/ui/disclosure'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { PrevizRunPayload, PrevizRunVariant } from '@/types/previz'
import { RUN_VARIANT_OPTIONS, type SceneRef } from './previzLogic'

export interface PrevizRunControlsProps {
  scenes: SceneRef[]
  disabled: boolean
  isRunning: boolean
  onRequestRun: (payload: PrevizRunPayload) => void
}

const sceneName = (s: SceneRef): string => (s.heading ? `${s.index + 1}. ${s.heading}` : `Scene ${s.index + 1}`)

function toggleId(prev: ReadonlySet<string>, id: string, on: boolean): Set<string> {
  const next = new Set(prev)
  if (on) next.add(id)
  else next.delete(id)
  return next
}

const SceneFilter = ({ scenes, selected, onToggle }: { scenes: SceneRef[]; selected: ReadonlySet<string>; onToggle: (id: string, on: boolean) => void }) => (
  <Disclosure
    title={<span className="text-xs text-muted-foreground">Limit to scenes</span>}
    summary={<span className="text-[11px] text-muted-foreground">{selected.size === 0 ? 'All scenes' : `${selected.size} selected`}</span>}
    triggerClassName="py-1"
    contentClassName="flex flex-wrap gap-x-4 gap-y-2 pb-1 pt-2"
  >
    {scenes.map((s) => (
      <label key={s.id} className="flex cursor-pointer items-center gap-2 text-xs text-foreground">
        <Checkbox checked={selected.has(s.id)} onCheckedChange={(on) => onToggle(s.id, on)} aria-label={sceneName(s)} />
        <span className="max-w-[16rem] truncate">{sceneName(s)}</span>
      </label>
    ))}
  </Disclosure>
)

/** Variant selector, optional scene filter, force toggle and Run (confirmation is owned by the panel). */
export const PrevizRunControls = ({ scenes, disabled, isRunning, onRequestRun }: PrevizRunControlsProps) => {
  const [variant, setVariant] = useState<PrevizRunVariant>('previz_only')
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [force, setForce] = useState(false)
  const submit = () => onRequestRun({ variant, scene_ids: selected.size > 0 ? [...selected] : null, force })
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Select className="w-56" value={variant} options={RUN_VARIANT_OPTIONS} onChange={(v) => setVariant(v as PrevizRunVariant)} />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <Switch checked={force} onCheckedChange={setForce} aria-label="Force re-render" />Force re-render
        </label>
        <Button size="sm" icon={isRunning ? Loader2 : Play} disabled={disabled} onClick={submit}>{isRunning ? 'Running…' : 'Run previz'}</Button>
      </div>
      {scenes.length > 1 && <SceneFilter scenes={scenes} selected={selected} onToggle={(id, on) => setSelected((p) => toggleId(p, id, on))} />}
    </div>
  )
}
