import * as React from 'react'
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Link as LinkIcon, Check as CheckIcon, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Copyable anchor link icon — shows on hover, copies full URL on click */
export const AnchorLink = ({ id }: { id: string }) => {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault()
        const url = `${window.location.origin}${window.location.pathname}#${id}`
        navigator.clipboard.writeText(url)
        window.history.replaceState(null, '', `#${id}`)
        document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-accent"
      title="Copy link"
    >
      {copied ? <CheckIcon size={14} /> : <LinkIcon size={14} />}
    </button>
  )
}

/** Section heading with hover-copyable anchor link */
export const AnchorHeading = ({
  id,
  children,
  className,
  as: Tag = 'h3',
  onClick,
}: {
  id: string
  children: React.ReactNode
  className?: string
  as?: 'h2' | 'h3' | 'h4' | 'button'
  onClick?: () => void
}) => (
  <Tag
    id={id}
    className={cn('group flex items-center gap-2', className)}
    {...(onClick ? { onClick, type: 'button' as const } : {})}
  >
    {children}
    <AnchorLink id={id} />
  </Tag>
)

export const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('flex flex-col space-y-1.5 px-5 pt-5 pb-3', className)}
    {...props}
  />
))
CardHeader.displayName = 'CardHeader'

export const CardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h3
    ref={ref}
    className={cn('text-base font-heading font-bold leading-none tracking-tight text-foreground', className)}
    {...props}
  />
))
CardTitle.displayName = 'CardTitle'

export const CardDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    className={cn('text-xs text-muted-foreground leading-relaxed', className)}
    {...props}
  />
))
CardDescription.displayName = 'CardDescription'

export const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('px-5 py-4 text-sm text-muted-foreground flex-1', className)} {...props} />
))
CardContent.displayName = 'CardContent'

export const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn('px-5 py-4 bg-muted/20 border-t border-border flex items-center justify-end gap-2 rounded-b-xl', className)}
    {...props}
  />
))
CardFooter.displayName = 'CardFooter'

export interface CardProps {
  id?: string
  title?: string
  icon?: LucideIcon
  children: React.ReactNode
  actions?: React.ReactNode
  className?: string
  interactive?: boolean
}

export const Card = ({
  id,
  title,
  icon: Icon,
  children,
  actions,
  className,
  interactive = true,
}: CardProps) => (
  <motion.div
    id={id}
    initial={{ opacity: 0, y: 10 }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true }}
    transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
    className={cn('glass bg-card rounded-xl shadow-sm transition-all duration-300 flex flex-col', interactive && 'card-interactive', className)}
  >
    {(title || Icon) && (
      <div className="px-5 pt-5 pb-3 flex items-center gap-2.5 group">
        {Icon && (
          <div className="p-1.5 rounded-[5px] bg-gradient-to-br from-orange-500/20 to-amber-500/10 text-accent-dark border border-orange-500/20">
            <Icon size={18} />
          </div>
        )}
        {title && <h3 className="text-base font-heading font-bold text-foreground">{title}</h3>}
        {id && <AnchorLink id={id} />}
      </div>
    )}
    <div className="px-5 py-4 text-sm text-muted-foreground flex-1">{children}</div>
    {actions && (
      <div className="px-5 py-4 bg-muted/20 border-t border-border flex justify-end gap-2 rounded-b-xl">{actions}</div>
    )}
  </motion.div>
)
