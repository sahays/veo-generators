import * as React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface DisclosureProps {
  /** Always-visible trigger content (left side). */
  title: React.ReactNode
  /** Optional right-aligned summary shown in the trigger row (counts, status). */
  summary?: React.ReactNode
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  children: React.ReactNode
  className?: string
  triggerClassName?: string
  contentClassName?: string
}

function useControllableOpen(open: boolean | undefined, defaultOpen: boolean, onOpenChange?: (o: boolean) => void) {
  const [inner, setInner] = React.useState(defaultOpen)
  const isOpen = open ?? inner
  const toggle = React.useCallback(() => {
    const next = !isOpen
    if (open === undefined) setInner(next)
    onOpenChange?.(next)
  }, [isOpen, open, onOpenChange])
  return { isOpen, toggle }
}

const DisclosureRegion = ({ id, isOpen, className, children }: { id: string; isOpen: boolean; className?: string; children: React.ReactNode }) => (
  <AnimatePresence initial={false}>
    {isOpen && (
      <motion.div
        id={id}
        role="region"
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: 'auto', opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className="overflow-hidden"
      >
        <div className={className}>{children}</div>
      </motion.div>
    )}
  </AnimatePresence>
)

/**
 * Accessible progressive-disclosure row: a full-width trigger with `aria-expanded`
 * and an animated region revealed on demand.
 */
export const Disclosure = ({
  title, summary, open, defaultOpen = false, onOpenChange, children, className, triggerClassName, contentClassName,
}: DisclosureProps) => {
  const { isOpen, toggle } = useControllableOpen(open, defaultOpen, onOpenChange)
  const regionId = React.useId()
  return (
    <div className={cn('min-w-0', className)}>
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls={regionId}
        onClick={toggle}
        className={cn(
          'group flex w-full items-center gap-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg',
          triggerClassName,
        )}
      >
        <div className="min-w-0 flex-1">{title}</div>
        {summary && <div className="shrink-0 text-xs text-muted-foreground">{summary}</div>}
        <ChevronDown size={16} className={cn('shrink-0 text-muted-foreground transition-transform duration-200', isOpen && 'rotate-180')} />
      </button>
      <DisclosureRegion id={regionId} isOpen={isOpen} className={contentClassName}>{children}</DisclosureRegion>
    </div>
  )
}
