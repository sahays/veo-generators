import { motion } from 'framer-motion'
import { Clock, Play, Tag } from 'lucide-react'
import { AnchorHeading } from '@/components/Common'
import { cn, parseTimestamp } from '@/lib/utils'
import type { KeyMoment } from '@/types/project'

interface Props {
  moments: KeyMoment[]
  activeMomentIndex: number | null
  onSeek: (index: number) => void
}

const formatTimestamp = (ts: string) => {
  const secs = parseTimestamp(ts)
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export const KeyMomentsTimeline = ({ moments, activeMomentIndex, onSeek }: Props) => (
  <div className="space-y-4">
    <div className="flex items-center gap-2">
      <Clock size={16} className="text-accent-dark" />
      <AnchorHeading
        id="key-moments-list"
        className="text-base font-heading font-bold text-foreground"
      >
        {moments.length} Key Moments
      </AnchorHeading>
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {moments.map((moment, i) => (
        <motion.button
          key={i}
          onClick={() => onSeek(i)}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.03 }}
          className={cn(
            'text-left p-4 rounded-xl border transition-all cursor-pointer',
            'hover:border-accent/50 hover:bg-accent/5',
            activeMomentIndex === i
              ? 'border-accent bg-accent/10 shadow-md ring-2 ring-accent/20'
              : 'border-border bg-card',
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[10px] font-mono font-bold text-accent-dark bg-accent/10 px-1.5 py-0.5 rounded flex items-center gap-1">
              <Play size={8} className={cn(activeMomentIndex === i ? 'fill-accent-dark' : '')} />
              {formatTimestamp(moment.timestamp_start)} - {formatTimestamp(moment.timestamp_end)}
            </span>
            {moment.category && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-600 border border-indigo-500/20">
                {moment.category}
              </span>
            )}
          </div>

          <p className="text-xs font-bold text-foreground line-clamp-1 mb-1">{moment.title}</p>
          <p className="text-[11px] text-muted-foreground line-clamp-3 leading-relaxed mb-2">
            {moment.description}
          </p>

          {moment.tags && moment.tags.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <Tag size={8} className="text-muted-foreground shrink-0" />
              {moment.tags.map((tag, j) => (
                <span
                  key={j}
                  className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </motion.button>
      ))}
    </div>
  </div>
)
