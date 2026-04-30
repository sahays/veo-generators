import { Loader2, AlertCircle, Play, Mic, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { VOICE_TURN_MARKER, type AvatarTurn } from '@/types/avatar'

interface AvatarTurnBubbleProps {
  turn: AvatarTurn
  onPlay?: () => void
}

function formatDuration(start?: string, end?: string): string | null {
  if (!start || !end) return null
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (!Number.isFinite(ms) || ms <= 0) return null
  if (ms < 1000) return `${ms} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rs = Math.round(s % 60)
  return `${m}m ${rs}s`
}

export const AvatarTurnBubble = ({ turn, onPlay }: AvatarTurnBubbleProps) => {
  const isVoice = turn.question === VOICE_TURN_MARKER
  const duration = formatDuration(turn.createdAt, turn.completedAt)
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <div
          className={cn(
            'max-w-[80%] px-3 py-2 rounded-2xl rounded-tr-sm text-sm',
            isVoice
              ? 'bg-accent/15 text-muted-foreground inline-flex items-center gap-1.5'
              : 'bg-accent/15 text-foreground',
          )}
        >
          {isVoice ? (
            <>
              <Mic size={12} />
              <span className="text-xs">Voice message</span>
            </>
          ) : (
            turn.question
          )}
        </div>
      </div>
      <div className="flex justify-start">
        <div
          className={cn(
            'max-w-[80%] px-3 py-2 rounded-2xl rounded-tl-sm text-sm border',
            turn.status === 'failed'
              ? 'bg-red-500/10 border-red-500/30 text-red-500'
              : 'bg-muted/40 border-border text-foreground',
          )}
        >
          <p className="leading-relaxed">{turn.answer_text}</p>
          <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground flex-wrap">
            {turn.status === 'pending' || turn.status === 'generating' ? (
              <>
                <Loader2 size={10} className="animate-spin" />
                <span>Generating video…</span>
              </>
            ) : turn.status === 'failed' ? (
              <>
                <AlertCircle size={10} />
                <span>{turn.error_message || 'Render failed'}</span>
              </>
            ) : turn.video_signed_url ? (
              <button
                onClick={onPlay}
                className="flex items-center gap-1 text-accent-dark hover:underline cursor-pointer"
              >
                <Play size={10} /> Watch reply
              </button>
            ) : null}
            {duration && (turn.status === 'completed' || turn.status === 'failed') && (
              <span className="flex items-center gap-1 opacity-70">
                <Clock size={10} /> {duration}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
