import * as React from 'react'
import * as MenuPrimitive from '@radix-ui/react-dropdown-menu'
import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

export const DropdownMenu = MenuPrimitive.Root
export const DropdownMenuTrigger = MenuPrimitive.Trigger
export const DropdownMenuGroup = MenuPrimitive.Group

export const DropdownMenuContent = React.forwardRef<
  React.ElementRef<typeof MenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Content>
>(({ className, sideOffset = 6, align = 'end', ...props }, ref) => (
  <MenuPrimitive.Portal>
    <MenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      align={align}
      className={cn(
        'z-50 min-w-[13rem] overflow-hidden rounded-xl bg-card p-1.5 text-foreground shadow-xl ring-1 ring-black/10 dark:ring-white/10',
        'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
        className,
      )}
      {...props}
    />
  </MenuPrimitive.Portal>
))
DropdownMenuContent.displayName = MenuPrimitive.Content.displayName

export const DropdownMenuItem = React.forwardRef<
  React.ElementRef<typeof MenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Item> & { icon?: LucideIcon }
>(({ className, icon: Icon, children, ...props }, ref) => (
  <MenuPrimitive.Item
    ref={ref}
    className={cn(
      'flex cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs outline-none transition-colors',
      'focus:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-45',
      className,
    )}
    {...props}
  >
    {Icon && <Icon size={14} className="shrink-0 text-muted-foreground" />}
    <span className="flex-1">{children}</span>
  </MenuPrimitive.Item>
))
DropdownMenuItem.displayName = MenuPrimitive.Item.displayName

export const DropdownMenuLabel = ({ className, ...props }: React.ComponentPropsWithoutRef<typeof MenuPrimitive.Label>) => (
  <MenuPrimitive.Label className={cn('px-2.5 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground', className)} {...props} />
)

export const DropdownMenuSeparator = ({ className, ...props }: React.ComponentPropsWithoutRef<typeof MenuPrimitive.Separator>) => (
  <MenuPrimitive.Separator className={cn('my-1 h-px bg-border/70', className)} {...props} />
)
