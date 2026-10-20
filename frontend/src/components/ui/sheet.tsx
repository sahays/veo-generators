import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: React.ReactNode
  footer?: React.ReactNode
  widthClass?: string
}

/** Right-side drawer (Radix Dialog) for on-demand details; focus-trapped and Esc-dismissable. */
export const Sheet = ({ open, onClose, title, subtitle, children, footer, widthClass = 'sm:max-w-xl' }: SheetProps) => (
  <DialogPrimitive.Root open={open} onOpenChange={(o) => !o && onClose()}>
    <AnimatePresence>
      {open && (
        <DialogPrimitive.Portal forceMount>
          <DialogPrimitive.Overlay asChild>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.16 }} className="fixed inset-0 z-50 bg-black/45 backdrop-blur-[2px]" />
          </DialogPrimitive.Overlay>
          <DialogPrimitive.Content asChild>
            <motion.aside
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 36 }}
              className={cn('fixed inset-y-0 right-0 z-50 flex w-full flex-col bg-card shadow-2xl focus:outline-none', widthClass)}
            >
              <header className="flex items-start justify-between gap-3 px-6 pb-4 pt-5">
                <div className="min-w-0">
                  <DialogPrimitive.Title className="truncate text-base font-heading font-semibold tracking-tight text-foreground">{title}</DialogPrimitive.Title>
                  <DialogPrimitive.Description className={subtitle ? 'mt-0.5 text-xs text-muted-foreground' : 'sr-only'}>{subtitle || title}</DialogPrimitive.Description>
                </div>
                <DialogPrimitive.Close aria-label="Close details" className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <X size={18} />
                </DialogPrimitive.Close>
              </header>
              <div className="flex-1 overflow-y-auto px-6 pb-6">{children}</div>
              {footer && <footer className="flex items-center justify-end gap-2 bg-muted/30 px-6 py-3">{footer}</footer>}
            </motion.aside>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      )}
    </AnimatePresence>
  </DialogPrimitive.Root>
)
