import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  'transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 cursor-pointer disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45 disabled:grayscale-[0.4]',
  {
    variants: {
      variant: {
        primary:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium btn-primary text-white shadow-sm',
        default:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium btn-primary text-white shadow-sm',
        ai: 'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium btn-ai text-white shadow-sm',
        secondary:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium btn-secondary-boost text-foreground hover:text-foreground',
        outline:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium border border-border bg-card/60 text-foreground hover:border-accent/45 hover:bg-accent/10',
        ghost:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium btn-ghost bg-transparent text-foreground',
        destructive:
          'btn-icon-spring inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium bg-gradient-to-r from-red-600 via-red-500 to-orange-600 text-white shadow-sm hover:shadow-red-500/25',
        link: 'btn-icon-spring inline-flex items-center gap-1.5 bg-transparent text-muted-foreground hover:text-foreground font-medium',
        unstyled: '',
      },
      size: {
        xs: 'h-7 px-2.5 py-1 text-xs rounded-[4px]',
        sm: 'h-8 px-3 py-1.5 text-xs rounded-[5px]',
        md: 'px-4 py-2 text-sm rounded-[5px]',
        lg: 'px-5 py-2.5 text-sm rounded-[6px]',
        icon: 'h-8 w-8 p-0 rounded-[5px]',
        none: '',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
)

type MotionButtonProps = React.ComponentPropsWithoutRef<typeof motion.button>

export interface ButtonProps
  extends Omit<MotionButtonProps, 'children'>,
    VariantProps<typeof buttonVariants> {
  children?: React.ReactNode
  icon?: LucideIcon
  iconSize?: number
  asChild?: boolean
  href?: string
  download?: boolean | string
  target?: string
  rel?: string
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      children,
      className,
      variant = 'primary',
      size = 'md',
      icon: Icon,
      iconSize,
      asChild = false,
      href,
      download,
      target,
      rel,
      type = 'button',
      ...props
    },
    ref,
  ) => {
    const resolvedSize = variant === 'unstyled' || variant === 'link' ? 'none' : size
    const resolvedIconSize = iconSize ?? (size === 'xs' || size === 'sm' ? 14 : 16)
    const classes = cn(buttonVariants({ variant, size: resolvedSize }), className)
    const content = (
      <>
        {Icon && (
          <span className="btn-icon inline-flex items-center shrink-0">
            <Icon size={resolvedIconSize} />
          </span>
        )}
        {children}
      </>
    )

    if (asChild) {
      return (
        <Slot className={classes} ref={ref as React.Ref<HTMLElement>}>
          {children}
        </Slot>
      )
    }

    if (href) {
      return (
        <motion.a
          href={href}
          download={download}
          target={target}
          rel={rel}
          whileHover={!props.disabled && variant !== 'unstyled' ? { scale: 1.015, y: -1 } : undefined}
          whileTap={!props.disabled ? { scale: 0.98, y: 0.5 } : undefined}
          transition={{ type: 'spring', stiffness: 420, damping: 20 }}
          className={classes}
          onClick={props.onClick as unknown as React.MouseEventHandler<HTMLAnchorElement>}
          title={props.title}
        >
          {content}
        </motion.a>
      )
    }

    return (
      <motion.button
        ref={ref}
        type={type}
        whileHover={!props.disabled && variant !== 'unstyled' ? { scale: 1.015, y: -1 } : undefined}
        whileTap={!props.disabled ? { scale: 0.98, y: 0.5 } : undefined}
        transition={{ type: 'spring', stiffness: 420, damping: 20 }}
        className={classes}
        {...props}
      >
        {content}
      </motion.button>
    )
  },
)
Button.displayName = 'Button'
