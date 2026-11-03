import { forwardRef } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, type ButtonProps } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { selectBusyKey, selectLockLabel, selectLocked, useRunPoller, useRunSelector } from './ProductionRunContext'

export interface RunActionButtonProps extends ButtonProps {
  /** Spin while the live (or starting) run is on this stage. */
  stage?: string
  /** Spin while the live (or starting) run carries this label (wins over `stage`). */
  runLabel?: string
  /** Extra local pending flag (e.g. a per-item request). */
  pending?: boolean
}

/**
 * A run-starting button: disabled while any run is live or starting (with a tooltip naming
 * it), and spinning immediately on click via the poller's optimistic state.
 */
export const RunActionButton = forwardRef<HTMLButtonElement, RunActionButtonProps>(
  ({ stage, runLabel, pending, icon, disabled, className, ...rest }, ref) => {
    const poller = useRunPoller()
    const locked = useRunSelector(poller, selectLocked)
    const lockLabel = useRunSelector(poller, selectLockLabel)
    const busyKey = useRunSelector(poller, selectBusyKey)
    const matches = runLabel ? lockLabel === runLabel : !!stage && busyKey === stage
    const spinning = !!pending || (locked && matches)
    const button = (
      <Button
        ref={ref} {...rest} icon={spinning ? Loader2 : icon} aria-busy={spinning || undefined}
        className={cn(className, spinning && '[&_.btn-icon_svg]:animate-spin')} disabled={disabled || locked}
      />
    )
    if (!locked || !lockLabel) return button
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className="inline-flex rounded-[5px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{button}</span>
        </TooltipTrigger>
        <TooltipContent>A run is in progress: {lockLabel}</TooltipContent>
      </Tooltip>
    )
  },
)
RunActionButton.displayName = 'RunActionButton'
