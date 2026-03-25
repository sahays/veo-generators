import { Select } from '@/components/UI'

interface PromptSelectorProps {
  prompts: { id: string; name: string; version: number }[]
  value: string
  onChange: (id: string) => void
  placeholder?: string
  emptyMessage?: string
}

export function PromptSelector({
  prompts,
  value,
  onChange,
  placeholder = 'Default prompt (or select one)...',
  emptyMessage,
}: PromptSelectorProps): JSX.Element {
  return (
    <>
      <Select
        value={value}
        onChange={onChange}
        options={prompts.map((p) => ({
          value: p.id,
          label: p.name,
          description: `Version ${p.version}`,
        }))}
        placeholder={placeholder}
      />
      {prompts.length === 0 && emptyMessage && (
        <p className="text-xs text-muted-foreground">{emptyMessage}</p>
      )}
    </>
  )
}
