import { motion } from 'framer-motion'
import { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

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
    primary: "bg-accent text-slate-900 hover:bg-accent-dark shadow-sm",
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
  title?: string
  icon?: LucideIcon
  children: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

export const Card = ({ title, icon: Icon, children, actions, className }: CardProps) => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      className={cn(
        "glass bg-card rounded-xl shadow-sm transition-all duration-300 overflow-hidden flex flex-col",
        className
      )}
    >
      {/* Header */}
      {(title || Icon) && (
        <div className="px-5 pt-5 pb-3 flex items-center gap-2.5">
          {Icon && <Icon className="text-accent-dark" size={20} />}
          {title && <h3 className="text-base font-heading font-bold text-foreground">{title}</h3>}
        </div>
      )}
      
      {/* Body */}
      <div className="px-5 py-4 text-sm text-muted-foreground flex-1">
        {children}
      </div>

      {/* Footer */}
      {actions && (
        <div className="px-5 py-4 bg-muted/20 border-t border-border flex justify-end gap-2">
          {actions}
        </div>
      )}
    </motion.div>
  )
}
