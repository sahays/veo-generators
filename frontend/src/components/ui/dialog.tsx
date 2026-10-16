import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { motion, AnimatePresence } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogPortal = DialogPrimitive.Portal
export const DialogClose = DialogPrimitive.Close

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: React.ReactNode
  footer?: React.ReactNode
  maxWidth?: string
}

/**
 * Unified Shadcn + Radix Dialog / Modal with Framer Motion spring physics
 * and a gradient top accent line. Replaces the duplicate Modal definitions.
 */
export const Modal = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = 'max-w-2xl',
}: ModalProps) => {
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <AnimatePresence>
        {isOpen && (
          <DialogPortal forceMount>
            <DialogPrimitive.Overlay asChild>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                onClick={onClose}
                className="fixed inset-0 z-50 bg-black/65 backdrop-blur-sm"
              />
            </DialogPrimitive.Overlay>
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
              <DialogPrimitive.Content asChild>
                <motion.div
                  initial={{ opacity: 0, scale: 0.94, y: 18 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95, y: 14 }}
                  transition={{ type: 'spring', stiffness: 420, damping: 28 }}
                  className={cn(
                    'pointer-events-auto relative w-full bg-card rounded-2xl shadow-2xl border border-border flex flex-col overflow-hidden max-h-[90vh] focus:outline-none',
                    maxWidth,
                  )}
                >
                  {/* Gradient top accent line */}
                  <div className="h-1 w-full bg-gradient-to-r from-orange-700 via-orange-500 to-amber-400" />
                  <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                    <div>
                      <DialogPrimitive.Title className="text-lg font-heading font-bold text-foreground">
                        {title}
                      </DialogPrimitive.Title>
                      {subtitle ? (
                        <DialogPrimitive.Description className="text-xs text-muted-foreground mt-0.5">
                          {subtitle}
                        </DialogPrimitive.Description>
                      ) : (
                        <DialogPrimitive.Description className="sr-only">
                          {title}
                        </DialogPrimitive.Description>
                      )}
                    </div>
                    <DialogPrimitive.Close
                      onClick={onClose}
                      className="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
                    >
                      <X size={18} />
                    </DialogPrimitive.Close>
                  </div>
                  <div className="flex-1 overflow-y-auto p-6">{children}</div>
                  {footer && (
                    <div className="px-6 py-4 bg-muted/20 border-t border-border flex items-center justify-end gap-3">
                      {footer}
                    </div>
                  )}
                </motion.div>
              </DialogPrimitive.Content>
            </div>
          </DialogPortal>
        )}
      </AnimatePresence>
    </Dialog>
  )
}
