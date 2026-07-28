import { motion } from 'framer-motion'
import { Archive, Film, Languages } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'

const STATUS_STYLES: Record<string, string> = {
  pending: 'text-slate-600 bg-slate-500/10',
  generating: 'text-blue-600 bg-blue-500/10',
  completed: 'text-emerald-600 bg-emerald-500/10',
  partial: 'text-amber-600 bg-amber-500/10',
  failed: 'text-red-600 bg-red-500/10',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  generating: 'Dubbing',
  completed: 'Completed',
  partial: 'Partial',
  failed: 'Failed',
}

interface DubVariant {
  language_code: string
  status: string
  output_signed_url?: string
}

interface DubRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  duration_sec?: number
  variants?: DubVariant[]
  source_signed_url?: string
  usage?: { cost_usd?: number }
  createdAt: string
  completedAt?: string
}

const VARIANT_DOT: Record<string, string> = {
  completed: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/25',
  failed: 'bg-red-500/15 text-red-600 border-red-500/25',
  generating: 'bg-blue-500/15 text-blue-600 border-blue-500/25',
  pending: 'bg-slate-500/15 text-slate-600 border-slate-500/25',
}

const DubCard = ({ record, onClick, onArchive, showArchive }: {
  record: DubRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => {
  // Prefer a completed dub for the thumbnail so the card shows the actual
  // deliverable; fall back to the source before showing a placeholder.
  const preview =
    record.variants?.find((v) => v.status === 'completed')?.output_signed_url ||
    record.source_signed_url

  return (
    <motion.button
      key={record.id}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-4 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full flex gap-4"
    >
      <div className="w-24 shrink-0 aspect-video rounded-lg overflow-hidden bg-muted border border-border/50 flex items-center justify-center">
        {preview ? (
          <video
            src={`${preview}#t=0.1`}
            muted
            playsInline
            preload="metadata"
            className="w-full h-full object-cover"
          />
        ) : (
          <Film size={16} className="text-muted-foreground/40" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
          <span className={cn(
            'flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0',
            STATUS_STYLES[record.status] || STATUS_STYLES.pending,
          )}>
            <Languages size={10} />
            {STATUS_LABELS[record.status] || record.status}
          </span>
          {record.status === 'generating' && (
            <span className="text-[9px] text-muted-foreground">{record.progress_pct}%</span>
          )}
          {record.variants?.map((v) => (
            <span
              key={v.language_code}
              className={cn(
                'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border',
                VARIANT_DOT[v.status] || VARIANT_DOT.pending,
              )}
            >
              {v.language_code}
            </span>
          ))}
        </div>

        <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-3">
          {record.display_name || record.source_filename || 'Untitled video'}
        </h4>

        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>{getTimeAgo(record.createdAt)}</span>
            {record.duration_sec ? (
              <>
                <span className="text-muted-foreground/50">&middot;</span>
                <span>{Math.round(record.duration_sec)}s</span>
              </>
            ) : null}
            {record.usage?.cost_usd ? (
              <>
                <span className="text-muted-foreground/50">&middot;</span>
                <span>${record.usage.cost_usd.toFixed(3)}</span>
              </>
            ) : null}
          </div>
          {showArchive && (
            <button
              onClick={onArchive}
              className="p-1 -m-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
              title="Archive"
            >
              <Archive size={12} />
            </button>
          )}
        </div>
      </div>
    </motion.button>
  )
}

export const DubbingLandingPage = () => (
  <LandingPageShell<DubRecord>
    title="Dubbing"
    subtitle="Dub a video into Spanish, Portuguese, German or Hindi with Gemini Live Translate"
    icon={Languages}
    fetchRecords={() => api.dubbing.list()}
    archiveRecord={(id) => api.dubbing.archive(id)}
    createPath="/dubbing/create"
    detailPath="/dubbing"
    buttonLabel="New Dub"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <DubCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No dubs yet"
    emptyDescription="Pick a video with spoken audio and choose target languages. Each language comes back as its own dubbed video with a transcript and subtitles."
  />
)
