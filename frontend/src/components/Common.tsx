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
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 400, damping: 17 }}
      className={cn(
        "flex items-center gap-2 px-4 py-2 rounded-md font-medium transition-all duration-200 disabled:opacity-50 cursor-pointer text-sm",
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
        "glass bg-card p-5 rounded-xl shadow-sm transition-all duration-300",
        className
      )}
    >
      {(title || Icon) && (
        <div className="flex items-center gap-2.5 mb-4">
          {Icon && <Icon className="text-accent-dark" size={20} />}
          {title && <h3 className="text-base font-heading font-bold text-foreground">{title}</h3>}
        </div>
      )}
      
      <div className="text-sm text-muted-foreground">
        {children}
      </div>

      {actions && (
        <div className="flex justify-end gap-2 pt-4 mt-4 border-t border-border">
          {actions}
        </div>
      )}
    </motion.div>
  )
}
