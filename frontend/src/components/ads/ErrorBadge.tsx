import { useState } from 'react'
import { AlertCircle, Check, Copy } from 'lucide-react'

export const ErrorBadge = ({ message }: { message: string }) => {
  const [copied, setCopied] = useState(false)
  const [showTooltip, setShowTooltip] = useState(false)

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation()
    navigator.clipboard.writeText(message)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="relative">
      <button
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={() => setShowTooltip(!showTooltip)}
        className="flex items-center gap-1 px-2 py-1 rounded-md bg-red-500/10 text-red-500 text-xs font-medium cursor-pointer"
      >
        <AlertCircle size={12} />
        Error!
      </button>
      {showTooltip && (
        <div className="absolute bottom-full left-0 mb-2 z-50 w-80 max-w-[90vw]">
          <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-[11px] text-foreground break-all leading-relaxed flex-1">
                {message}
              </p>
              <button
                onClick={handleCopy}
                className="shrink-0 p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                title="Copy error"
              >
                {copied ? (
                  <Check size={12} className="text-emerald-500" />
                ) : (
                  <Copy size={12} />
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
