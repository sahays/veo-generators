import React from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { NativeSelect } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  useDubbingLanguages,
  type ConfirmationJobParams,
} from './useChatWidgetActions'

const DURATION_OPTIONS = [
  { value: 60, label: '1m' },
  { value: 90, label: '1.5m' },
  { value: 120, label: '2m' },
  { value: 150, label: '2.5m' },
  { value: 180, label: '3m' },
]

const CONTENT_TYPE_OPTIONS = [
  { value: 'movies', label: 'Movies' },
  { value: 'documentaries', label: 'Documentaries' },
  { value: 'sports', label: 'Sports' },
  { value: 'podcasts', label: 'Podcasts' },
  { value: 'promos', label: 'Promos' },
  { value: 'news', label: 'News' },
  { value: 'other', label: 'Other' },
]

const ALL_RATIOS = ['16:9', '9:16', '1:1', '4:5', '4:3', '3:4']

export interface FieldRendererProps {
  params: ConfirmationJobParams
  resolved: Record<string, string>
  onChange: (p: ConfirmationJobParams) => void
  disabled: boolean
}

export const DisplayField: React.FC<{ label: string; value?: string }> = ({ label, value }) => (
  <div className="flex items-center justify-between gap-2 py-1">
    <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
    <span className="text-[11px] font-medium text-slate-700 dark:text-slate-200 truncate max-w-[60%] text-right">
      {value || 'Default'}
    </span>
  </div>
)

export const ToggleField: React.FC<{
  label: string
  checked?: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}> = ({ label, checked, onChange, disabled }) => (
  <label
    className={cn(
      'flex items-center justify-between gap-2 py-1 cursor-pointer',
      disabled && 'opacity-50 pointer-events-none',
    )}
  >
    <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
    <Button
      type="button"
      variant="unstyled"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-4 w-7 rounded-full transition-colors',
        checked ? 'bg-orange-500' : 'bg-slate-300 dark:bg-slate-600',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 left-0.5 h-3 w-3 rounded-full bg-white shadow transition-transform',
          checked && 'translate-x-3',
        )}
      />
    </Button>
  </label>
)

const DurationPills: React.FC<{
  selected?: number
  disabled: boolean
  onSelect: (v: number) => void
}> = ({ selected, disabled, onSelect }) => (
  <div className="py-1">
    <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Duration</span>
    <div className="flex gap-1 mt-1">
      {DURATION_OPTIONS.map((opt) => (
        <Button
          key={opt.value}
          variant="unstyled"
          disabled={disabled}
          onClick={() => onSelect(opt.value)}
          className={cn(
            'flex-1 py-1 rounded-[4px] text-[10px] font-bold transition-all',
            selected === opt.value
              ? 'bg-orange-500 text-white shadow-sm'
              : 'bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-400 dark:hover:bg-slate-600',
            disabled && 'pointer-events-none',
          )}
        >
          {opt.label}
        </Button>
      ))}
    </div>
  </div>
)

export const PromoFields: React.FC<FieldRendererProps> = ({
  params,
  resolved,
  onChange,
  disabled,
}) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    <DurationPills
      selected={params.target_duration}
      disabled={disabled}
      onSelect={(v) => onChange({ ...params, target_duration: v })}
    />
    <ToggleField
      label="Text overlays"
      checked={Boolean(params.text_overlay)}
      onChange={(v) => onChange({ ...params, text_overlay: v })}
      disabled={disabled}
    />
    <ToggleField
      label="Thumbnail card"
      checked={Boolean(params.generate_thumbnail)}
      onChange={(v) => onChange({ ...params, generate_thumbnail: v })}
      disabled={disabled}
    />
  </div>
)

export const ReframeFields: React.FC<FieldRendererProps> = ({
  params,
  resolved,
  onChange,
  disabled,
}) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    <div className="flex items-center justify-between gap-2 py-1">
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Content type</span>
      <NativeSelect
        value={params.content_type || 'movies'}
        onChange={(e) => onChange({ ...params, content_type: e.target.value })}
        disabled={disabled}
        className="h-7 w-36 px-2 py-0.5 text-[11px]"
      >
        {CONTENT_TYPE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </NativeSelect>
    </div>
    <ToggleField
      label="Blurred background"
      checked={Boolean(params.blurred_bg)}
      onChange={(v) => onChange({ ...params, blurred_bg: v })}
      disabled={disabled}
    />
  </div>
)

export const ProductionFields: React.FC<FieldRendererProps> = ({
  params,
  resolved,
  onChange,
  disabled,
}) => (
  <div className="space-y-1.5">
    <div>
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Name</span>
      <Input
        type="text"
        value={params.name || ''}
        onChange={(e) => onChange({ ...params, name: e.target.value })}
        disabled={disabled}
        className="mt-0.5 h-7 px-2 py-1 text-[11px]"
      />
    </div>
    <div>
      <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Concept</span>
      <Textarea
        value={params.base_concept || ''}
        onChange={(e) => onChange({ ...params, base_concept: e.target.value })}
        disabled={disabled}
        rows={2}
        className="mt-0.5 min-h-[48px] px-2 py-1 text-[11px]"
      />
    </div>
    {resolved.prompt_name && <DisplayField label="Prompt" value={resolved.prompt_name} />}
  </div>
)

export const KeyMomentsFields: React.FC<{ resolved: Record<string, string> }> = ({ resolved }) => (
  <div className="space-y-1">
    <DisplayField label="Source" value={resolved.source_name} />
    {resolved.prompt_name && <DisplayField label="Prompt" value={resolved.prompt_name} />}
  </div>
)

const ChipList: React.FC<{
  items: { key: string; label: string }[]
  selected: string[]
  disabled: boolean
  onToggle: (key: string) => void
}> = ({ items, selected, disabled, onToggle }) => (
  <div className="flex flex-wrap gap-1 mt-1">
    {items.map((item) => (
      <Button
        key={item.key}
        variant="unstyled"
        disabled={disabled}
        onClick={() => onToggle(item.key)}
        className={cn(
          'px-2 py-0.5 rounded-[4px] text-[10px] font-bold transition-all',
          selected.includes(item.key)
            ? 'bg-orange-500 text-white'
            : 'bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-400',
          disabled && 'pointer-events-none',
        )}
      >
        {item.label}
      </Button>
    ))}
  </div>
)

export const AdaptsFields: React.FC<FieldRendererProps> = ({
  params,
  resolved,
  onChange,
  disabled,
}) => {
  const ratios: string[] = params.aspect_ratios || []
  const toggleRatio = (r: string) => {
    const next = ratios.includes(r) ? ratios.filter((x) => x !== r) : [...ratios, r]
    onChange({ ...params, aspect_ratios: next })
  }
  return (
    <div className="space-y-1">
      <DisplayField label="Source" value={resolved.source_name} />
      <div className="py-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">Aspect ratios</span>
        <ChipList
          items={ALL_RATIOS.map((r) => ({ key: r, label: r }))}
          selected={ratios}
          disabled={disabled}
          onToggle={toggleRatio}
        />
      </div>
      {resolved.preset_name && <DisplayField label="Preset" value={resolved.preset_name} />}
    </div>
  )
}

export const DubbingFields: React.FC<FieldRendererProps> = ({
  params,
  resolved,
  onChange,
  disabled,
}) => {
  const languages = useDubbingLanguages()
  const selected: string[] = params.target_languages || []
  const items = (languages.length > 0 ? languages : selected.map((c) => ({ code: c, label: c }))).map(
    (l) => ({ key: l.code, label: l.label }),
  )
  const toggleLang = (code: string) => {
    const next = selected.includes(code)
      ? selected.filter((c) => c !== code)
      : selected.length < 4 ? [...selected, code] : selected
    onChange({ ...params, target_languages: next })
  }
  return (
    <div className="space-y-1">
      <DisplayField label="Source" value={resolved.source_name} />
      <div className="py-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
          Target Languages (up to 4)
        </span>
        <ChipList items={items} selected={selected} disabled={disabled} onToggle={toggleLang} />
      </div>
    </div>
  )
}
