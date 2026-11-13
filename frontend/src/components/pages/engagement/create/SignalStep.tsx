import { useId } from 'react'
import { FileSpreadsheet, Loader2 } from 'lucide-react'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { BARC_CHOICE } from '@/types/engagement/createForm'
import { SIMULATED_LABEL } from '@/types/engagement/reportFormat'
import { useEngagementTemplates } from '../useEngagementTemplates'
import { BarcPanel } from './BarcPanel'
import { Sparkline } from './FormParts'
import type { EngagementForm } from './useEngagementForm'

interface SignalOptionProps {
  /** Name shared by the radios of the group. */
  group: string
  value: string
  checked: boolean
  onSelect: (value: string) => void
  title: string
  description: string
  /** Shown under the description: the template's sparkline, or an icon. */
  children?: React.ReactNode
}

/** One radio option drawn as a card. The whole card is the radio's label. */
function SignalOption({ group, value, checked, onSelect, title, description, children }: SignalOptionProps): JSX.Element {
  return (
    <label
      data-testid={`signal-option-${value}`}
      className={cn('flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-ring', checked ? 'border-accent bg-accent/5' : 'border-border bg-card hover:border-accent/40')}
    >
      <input type="radio" name={group} value={value} checked={checked} onChange={() => onSelect(value)} className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-orange-500" />
      <span className="min-w-0 flex-1 space-y-1.5">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="block text-xs leading-snug text-muted-foreground">{description}</span>
        {children}
      </span>
    </label>
  )
}

function TemplatesStatus({ loading, error }: { loading: boolean; error: string | null }): JSX.Element | null {
  if (loading) {
    return (
      <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 size={14} aria-hidden className="animate-spin motion-reduce:animate-none" /> Loading templates…
      </p>
    )
  }
  return error ? <ErrorDisplay error={`${error}. You can still upload a BARC file.`} /> : null
}

/**
 * Step 2: the engagement signal. One radio per built-in template (illustrative
 * curves), plus the option to upload measured BARC data instead.
 */
export function SignalStep({ form }: { form: EngagementForm }): JSX.Element {
  const group = useId()
  const { templates, loading, error } = useEngagementTemplates()
  const choice = form.state.signalChoice
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Templates are illustrative curves, not audience data; reports built on them are labelled <Badge variant="warning">{SIMULATED_LABEL}</Badge>. Upload a BARC file to use measured ratings instead.
      </p>
      <TemplatesStatus loading={loading} error={error} />
      <div role="radiogroup" aria-label="Engagement signal" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {templates.map((template) => (
          <SignalOption key={template.id} group={group} value={template.id} checked={choice === template.id} onSelect={form.setSignalChoice} title={template.label} description={template.description}>
            <Sparkline values={template.preview} />
          </SignalOption>
        ))}
        <SignalOption group={group} value={BARC_CHOICE} checked={choice === BARC_CHOICE} onSelect={form.setSignalChoice} title="Upload a BARC file" description="Optional. Use measured ratings from a BARC CSV export (TVR, Impressions, Reach) instead of a template.">
          <FileSpreadsheet size={22} aria-hidden className="text-muted-foreground" />
        </SignalOption>
      </div>
      {choice === BARC_CHOICE && <BarcPanel barc={form.state.barc} onChange={form.setBarc} />}
    </div>
  )
}
