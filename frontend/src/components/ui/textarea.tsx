import * as React from 'react'
import { cn } from '@/lib/utils'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, ...props }, ref) => {
    const textareaEl = (
      <textarea
        ref={ref}
        className={cn(
          'flex min-h-[96px] w-full rounded-[5px] border border-border bg-card px-3.5 py-2.5 text-sm text-foreground placeholder:text-muted-foreground transition-all duration-200',
          'hover:border-accent/40 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
          'disabled:cursor-not-allowed disabled:opacity-60',
          error && 'border-red-500/60 focus:border-red-500 focus:ring-red-500/20',
          className,
        )}
        {...props}
      />
    )

    if (!label && !error) return textareaEl

    return (
      <div className="space-y-1.5 w-full">
        {label && (
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1 block">
            {label}
          </label>
        )}
        {textareaEl}
        {error && <p className="text-[10px] text-red-500 ml-1">{error}</p>}
      </div>
    )
  },
)
Textarea.displayName = 'Textarea'
