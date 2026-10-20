import * as React from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface CheckboxProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  checked?: boolean
  indeterminate?: boolean
  loading?: boolean
  onCheckedChange?: (checked: boolean) => void
}

export const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ className, checked = false, indeterminate = false, loading = false, onCheckedChange, disabled, ...props }, ref) => {
    const state = loading ? 'loading' : checked ? 'checked' : indeterminate ? 'indeterminate' : 'unchecked'
    return (
      <button
        ref={ref}
        type="button"
        role="checkbox"
        aria-checked={indeterminate ? 'mixed' : checked}
        data-state={state}
        disabled={disabled}
        onClick={() => onCheckedChange?.(!checked)}
        className={cn(
          'peer relative inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60',
          checked
            ? 'border-emerald-400 bg-gradient-to-br from-emerald-500 to-teal-500 text-white shadow-[0_0_14px_rgba(16,185,129,0.45)]'
            : loading
              ? 'border-orange-400/80 bg-orange-500/15 text-orange-400 shadow-[0_0_12px_rgba(249,115,22,0.35)]'
              : 'border-border/80 bg-background/70 text-transparent hover:border-orange-500/50',
          className,
        )}
        {...props}
      >
        <AnimatePresence mode="wait" initial={false}>
          {checked && (
            <motion.span
              key="checked"
              initial={{ scale: 0.2, opacity: 0, rotate: -25 }}
              animate={{ scale: [0.2, 1.25, 1], opacity: 1, rotate: 0 }}
              exit={{ scale: 0.3, opacity: 0 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="flex items-center justify-center"
            >
              <Check className="h-3.5 w-3.5 stroke-[3]" />
            </motion.span>
          )}
          {!checked && loading && (
            <motion.span
              key="loading"
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.6 }}
              className="flex items-center justify-center"
            >
              <Loader2 className="h-3 w-3 animate-spin" />
            </motion.span>
          )}
        </AnimatePresence>
      </button>
    )
  },
)
Checkbox.displayName = 'Checkbox'
