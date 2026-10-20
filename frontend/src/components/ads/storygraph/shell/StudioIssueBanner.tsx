import { AlertTriangle, RefreshCw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Disclosure } from '@/components/ui/disclosure'

export interface StudioIssueBannerProps {
  message: string
  stage?: string | null
  canRetry: boolean
  isBusy: boolean
  onRetry: (stage: string) => void
  onDismiss: () => void
}

function headline(message: string): string {
  const first = message.split(/[\n.]/, 1)[0]?.trim() || message
  return first.length > 110 ? `${first.slice(0, 107)}…` : first
}

/** One-line error/warning banner; the full message is behind a "Show details" expander. */
export const StudioIssueBanner = ({ message, stage, canRetry, isBusy, onRetry, onDismiss }: StudioIssueBannerProps) => (
  <div role="alert" className="flex items-start gap-3 rounded-xl bg-red-500/10 px-4 py-3 text-sm">
    <AlertTriangle size={16} className="mt-0.5 shrink-0 text-red-500 dark:text-red-400" />
    <Disclosure
      className="flex-1"
      triggerClassName="text-left"
      title={
        <span className="block truncate text-foreground">
          {stage && <span className="font-medium">{stage}: </span>}
          {headline(message)}
        </span>
      }
      summary={<span className="text-[11px] underline-offset-2 group-hover:underline">Show details</span>}
      contentClassName="pt-2"
    >
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-background/60 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
        {message}
      </pre>
    </Disclosure>
    <div className="flex shrink-0 items-center gap-1">
      {canRetry && stage && (
        <Button size="xs" variant="outline" icon={RefreshCw} disabled={isBusy} onClick={() => onRetry(stage)}>
          Retry
        </Button>
      )}
      <Button size="icon" variant="ghost" icon={X} aria-label="Dismiss message" onClick={onDismiss} />
    </div>
  </div>
)
