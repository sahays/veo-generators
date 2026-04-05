import { useState } from 'react'
import { motion } from 'framer-motion'
import { LucideIcon, Link as LinkIcon, Check as CheckIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Copyable anchor link icon — shows on hover, copies full URL on click */
const AnchorLink = ({ id }: { id: string }) => {
  const [copied, setCopied] = useState(false)
  return (
    <button
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
export const AnchorHeading = ({ id, children, className, as: Tag = 'h3', onClick }: {
  id: string
  children: React.ReactNode
  className?: string
  as?: 'h2' | 'h3' | 'h4' | 'button'
  onClick?: () => void
}) => (
  <Tag id={id} className={cn("group flex items-center gap-2", className)} {...(onClick ? { onClick, type: 'button' as const } : {})}>
    {children}
    <AnchorLink id={id} />
  </Tag>
)

type MotionButtonProps = React.ComponentPropsWithoutRef<typeof motion.button>

interface ButtonProps extends Omit<MotionButtonProps, "children"> {
  children: React.ReactNode
  variant?: 'primary' | 'secondary' | 'ghost'
  icon?: LucideIcon
}

export const Button = ({ 
  children, 
  className, 
  variant = 'primary', 
  icon: Icon,
  ...props 
}: ButtonProps) => {
  const variants = {
    primary: "btn-primary text-white shadow-sm",
    secondary: "bg-muted text-foreground hover:bg-border",
    ghost: "bg-transparent hover:bg-accent-light text-foreground",
  }

  return (
    <motion.button
      whileHover={!props.disabled ? { scale: 1.02 } : {}}
      whileTap={!props.disabled ? { scale: 0.98 } : {}}
      transition={{ type: "spring", stiffness: 400, damping: 17 }}
      className={cn(
        "flex items-center gap-2 px-4 py-2 rounded-md font-medium transition-all duration-200 text-sm",
        "cursor-pointer disabled:cursor-not-allowed disabled:opacity-40 disabled:grayscale-[0.5]",
        variants[variant],
        className
      )}
      {...props}
    >
      {Icon && <Icon size={16} />}
      {children}
    </motion.button>
  )
}

interface CardProps {
  id?: string
  title?: string
  icon?: LucideIcon
  children: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

export const Card = ({ id, title, icon: Icon, children, actions, className }: CardProps) => {
  return (
    <motion.div
      id={id}
      initial={{ opacity: 0, y: 10 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      className={cn(
        "glass bg-card rounded-xl shadow-sm transition-all duration-300 flex flex-col",
        className
      )}
    >
      {/* Header */}
      {(title || Icon) && (
        <div className="px-5 pt-5 pb-3 flex items-center gap-2.5 group">
          {Icon && <Icon className="text-accent-dark" size={20} />}
          {title && <h3 className="text-base font-heading font-bold text-foreground">{title}</h3>}
          {id && <AnchorLink id={id} />}
        </div>
      )}
      
      {/* Body */}
      <div className="px-5 py-4 text-sm text-muted-foreground flex-1">
        {children}
      </div>

      {/* Footer */}
      {actions && (
        <div className="px-5 py-4 bg-muted/20 border-t border-border flex justify-end gap-2 rounded-b-xl">
          {actions}
        </div>
      )}
    </motion.div>
  )
}
