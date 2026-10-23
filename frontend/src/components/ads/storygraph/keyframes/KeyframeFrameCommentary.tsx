import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Link2, OctagonAlert, UserPen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { KeyframeFrameView } from '@/types/keyframes'
import { formatDrift, isLongCommentary, parseStateSummary, type EntityLine } from './keyframeCommentary'
import { KeyframeStatusBadge } from './KeyframeThumbs'

const EntityItem = ({ line }: { line: EntityLine }) => (
  <li>
    {line.who && <span className="font-medium text-foreground">{line.who}</span>}
    {line.who && ' — '}
    <span>{line.action}</span>
    {line.holding.length > 0 && <span className="text-muted-foreground"> · holding {line.holding.join(', ')}</span>}
  </li>
)

/** What is happening this second, one line per entity, clamped to 3 lines with "more". */
const StateLines = ({ summary }: { summary: string }) => {
  const [expanded, setExpanded] = useState(false)
  const lines = parseStateSummary(summary)
  if (lines.length === 0) return <p className="text-xs italic text-muted-foreground">No characters on screen.</p>
  const long = isLongCommentary(lines)
  return (
    <div className="space-y-0.5">
      <ul className={cn('space-y-0.5 text-xs leading-relaxed text-foreground/85', long && !expanded && 'line-clamp-3')}>
        {lines.map((l, i) => <EntityItem key={`${l.who}-${i}`} line={l} />)}
      </ul>
      {long && (
        <Button variant="link" size="none" className="text-[11px]" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'less' : 'more'}
        </Button>
      )}
    </div>
  )
}

/** Plan-check result: issues (red for manual edit, amber otherwise) or a green "Matches plan". */
const CheckResult = ({ frame }: { frame: KeyframeFrameView }) => {
  if (frame.issues.length === 0) {
    return <p className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"><CheckCircle2 size={13} aria-hidden />Matches plan</p>
  }
  const severe = frame.status === 'manual_edit'
  const Icon = severe ? OctagonAlert : AlertTriangle
  return (
    <ul className={cn('space-y-1 text-xs', severe ? 'text-red-600 dark:text-red-400' : 'text-amber-600 dark:text-amber-400')}>
      {frame.issues.map((issue) => (
        <li key={issue} className="flex gap-1.5"><Icon size={13} className="mt-0.5 shrink-0" aria-hidden /><span className="min-w-0">{issue}</span></li>
      ))}
    </ul>
  )
}

/** Header row of the commentary: t=Ns, status, shared / human-edit chips. */
export const FrameChips = ({ frame }: { frame: KeyframeFrameView }) => (
  <div className="flex flex-wrap items-center gap-1.5">
    <span className="font-mono text-sm font-semibold tabular-nums text-foreground">t={frame.t}s</span>
    <KeyframeStatusBadge status={frame.status} />
    {frame.shared_from && <Badge variant="indigo" title={`Shared from ${frame.shared_from}`}><Link2 size={10} aria-hidden />Shared from previous clip</Badge>}
    {frame.edited_by === 'human' && <Badge variant="steel"><UserPen size={10} aria-hidden />Human edit</Badge>}
  </div>
)

/** Commentary block under each keyframe image. */
export const KeyframeFrameCommentary = ({ frame }: { frame: KeyframeFrameView }) => {
  const drift = formatDrift(frame.drift)
  const attempts = `${frame.attempts} attempt${frame.attempts === 1 ? '' : 's'}`
  return (
    <div className="space-y-2.5">
      <FrameChips frame={frame} />
      <StateLines summary={frame.state_summary} />
      <CheckResult frame={frame} />
      <p className="font-mono text-[10px] text-muted-foreground">{drift ? `drift ${drift} · ${attempts}` : attempts}</p>
    </div>
  )
}
