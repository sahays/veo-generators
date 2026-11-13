import { BarChart3, FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { SignalBadgeText } from '@/types/engagement/reportFormat'

export interface SignalBadgeProps {
  text: SignalBadgeText
  /** Leave out the template label / file name (where space is tight). */
  compact?: boolean
  className?: string
}

/**
 * Where the engagement curve comes from. Template curves are illustrative, so
 * their badge always reads "Template (simulated)"; a BARC badge names the file.
 */
export function SignalBadge({ text, compact = false, className }: SignalBadgeProps): JSX.Element {
  const Icon = text.simulated ? FlaskConical : BarChart3
  const detail = compact ? '' : text.detail
  const title = text.simulated ? 'Illustrative template curve, not audience measurement' : 'Measured audience data from a BARC file'
  return (
    <Badge variant={text.simulated ? 'warning' : 'indigo'} title={title} data-testid="signal-badge" data-simulated={text.simulated} className={cn('max-w-full', className)}>
      <Icon size={10} aria-hidden className="shrink-0" />
      <span className="truncate">
        {text.kind}
        {detail && <span className="font-normal"> · {detail}</span>}
      </span>
    </Badge>
  )
}
