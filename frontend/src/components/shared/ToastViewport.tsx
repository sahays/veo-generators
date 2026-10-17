import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { useToastStore, type ToastItem, type ToastVariant } from '@/store/useToastStore'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const VARIANT_CONFIG: Record<
  ToastVariant,
  { icon: typeof Info; bar: string; iconColor: string }
> = {
  default: {
    icon: Info,
    bar: 'from-orange-700 via-orange-500 to-amber-400',
    iconColor: 'text-accent',
  },
  info: {
    icon: Info,
    bar: 'from-orange-600 via-orange-500 to-amber-400',
    iconColor: 'text-orange-400',
  },
  success: {
    icon: CheckCircle2,
    bar: 'from-emerald-500 to-teal-400',
    iconColor: 'text-emerald-500',
  },
  error: {
    icon: AlertCircle,
    bar: 'from-red-500 to-orange-500',
    iconColor: 'text-red-500',
  },
}

const ToastCard = ({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) => {
  const cfg = VARIANT_CONFIG[toast.variant] || VARIANT_CONFIG.default
  const Icon = cfg.icon
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.92, transition: { duration: 0.15 } }}
      transition={{ type: 'spring', stiffness: 420, damping: 26 }}
      className="pointer-events-auto relative overflow-hidden rounded-lg bg-popover border border-border shadow-xl p-3.5 flex items-start gap-3"
    >
      <div className={cn('absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r', cfg.bar)} />
      <Icon size={16} className={cn('shrink-0 mt-0.5', cfg.iconColor)} />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-heading font-bold text-foreground">{toast.title}</p>
        {toast.description && (
          <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{toast.description}</p>
        )}
      </div>
      <Button variant="ghost" size="icon" onClick={onDismiss} className="h-6 w-6 text-muted-foreground hover:text-foreground">
        <X size={13} />
      </Button>
    </motion.div>
  )
}

export const ToastViewport = () => {
  const { toasts, removeToast } = useToastStore()

  return (
    <div className="fixed bottom-4 right-4 z-[70] flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} onDismiss={() => removeToast(toast.id)} />
        ))}
      </AnimatePresence>
    </div>
  )
}
