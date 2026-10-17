import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'

interface ProgressBarProps {
  progress: number
  showSpinner?: boolean
}

export function ProgressBar({ progress, showSpinner = true }: ProgressBarProps): JSX.Element {
  return (
    <div className="space-y-2">
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-accent to-accent-dark"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5 }}
        />
      </div>
      {showSpinner && (
        <div className="flex justify-center">
          <Loader2 className="animate-spin text-accent" size={20} />
        </div>
      )}
    </div>
  )
}
