// Shared subcomponents for SceneItemGrid and SceneItemList.

import {
  AlertCircle,
  CheckCircle2,
  Loader2,
} from 'lucide-react'

export interface SceneItemHandlers {
  handleToggle: (updates: any) => void
  handleTextChange: (updates: any) => void
  handleGenerateFrame: (promptData?: any) => void | Promise<void>
  handleGenerateVideo: (promptData?: any) => void | Promise<void>
}

export const AudioToggle = ({
  checked,
  onChange,
  disabled,
  icon,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled: boolean
  icon: React.ReactNode
  label: string
}) => (
  <label className="flex items-center gap-1.5 cursor-pointer select-none">
    <input
      type="checkbox"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      disabled={disabled}
      className="accent-accent w-3.5 h-3.5"
    />
    {icon}
    <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
      {label}
    </span>
  </label>
)

export const StatusIcon = ({ status }: { status?: string }) => {
  if (status === 'generating')
    return <Loader2 size={10} className="animate-spin text-amber-500" />
  if (status === 'completed')
    return <CheckCircle2 size={10} className="text-emerald-500" />
  if (status === 'failed')
    return <AlertCircle size={10} className="text-red-500" />
  return null
}

export const StatusBadge = ({ status }: { status?: string }) => {
  if (status === 'generating') {
    return (
      <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-amber-500">
        <Loader2 size={10} className="animate-spin" /> Generating
      </span>
    )
  }
  if (status === 'completed') {
    return (
      <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-emerald-500">
        <CheckCircle2 size={10} /> Done
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="flex items-center gap-1 text-[9px] font-bold uppercase text-red-500">
        <AlertCircle size={10} /> Failed
      </span>
    )
  }
  return null
}
