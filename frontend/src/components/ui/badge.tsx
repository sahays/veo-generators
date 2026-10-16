import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

export const badgeVariants = cva(
  'badge-glow inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-all shrink-0',
  {
    variants: {
      variant: {
        default: 'bg-muted text-muted-foreground border border-border',
        accent: 'bg-accent/12 text-accent-dark border border-accent/25 font-semibold',
        steel: 'bg-orange-500/12 text-orange-400 border border-orange-500/25 font-semibold',
        ai: 'bg-gradient-to-r from-orange-700 via-orange-500 to-amber-500 text-white font-semibold border-0',
        success: 'bg-emerald-500/12 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20',
        warning: 'bg-amber-500/12 text-amber-600 dark:text-amber-400 border border-amber-500/20',
        destructive: 'bg-red-500/12 text-red-600 dark:text-red-400 border border-red-500/20',
        purple: 'bg-purple-500/12 text-purple-600 dark:text-purple-400 border border-purple-500/20',
        indigo: 'bg-indigo-500/12 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20',
        outline: 'text-foreground border border-border bg-transparent',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = ({ className, variant, ...props }: BadgeProps) => {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
