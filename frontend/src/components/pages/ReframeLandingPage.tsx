import { motion } from 'framer-motion'
import { Smartphone, Archive, Film } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { CONTENT_TYPE_BADGE } from '@/components/pages/reframe/contentTypes'

const STATUS_STYLES: Record<string, string> = {
  pending: 'text-slate-600 bg-slate-500/10',
  analyzing: 'text-amber-600 bg-amber-500/10',
  processing: 'text-blue-600 bg-blue-500/10',
  encoding: 'text-purple-600 bg-purple-500/10',
  completed: 'text-emerald-600 bg-emerald-500/10',
  failed: 'text-red-600 bg-red-500/10',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  analyzing: 'Analyzing',
  processing: 'Processing',
  encoding: 'Encoding',
  completed: 'Completed',
  failed: 'Failed',
}

interface ReframeRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  content_type?: string
  blurred_bg?: boolean
  source_signed_url?: string
  output_signed_url?: string
  usage?: { cost_usd?: number }
  createdAt: string
  completedAt?: string
}

const ReframeCard = ({ record, onClick, onArchive, showArchive }: {
  record: ReframeRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => {
  const typeBadge = record.content_type && record.content_type !== 'other'
    ? CONTENT_TYPE_BADGE[record.content_type]
    : null
  return (
    <motion.button
      key={record.id}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-4 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full flex gap-4"
    >
      {/* First-frame thumbnail of the 9:16 output */}
      <div className="w-16 shrink-0 aspect-[9/16] rounded-lg overflow-hidden bg-muted border border-border/50 flex items-center justify-center">
        {record.output_signed_url ? (
          <video
            src={`${record.output_signed_url}#t=0.1`}
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
            "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0",
            STATUS_STYLES[record.status] || STATUS_STYLES.pending
          )}>
            <Smartphone size={10} />
            {STATUS_LABELS[record.status] || record.status}
          </span>
          {record.status === 'processing' || record.status === 'encoding' || record.status === 'analyzing' ? (
            <span className="text-[9px] text-muted-foreground">{record.progress_pct}%</span>
          ) : null}
          {typeBadge && (
            <span className={cn("px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border", typeBadge.className)}>
              {typeBadge.label}
            </span>
          )}
          <span className={cn(
            "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border",
            record.blurred_bg
              ? "bg-purple-500/10 text-purple-600 border-purple-500/20"
              : "bg-slate-500/10 text-slate-600 border-slate-500/20",
          )}>
            {record.blurred_bg ? 'Blurred 4:5' : 'Crop 9:16'}
          </span>
        </div>

        <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-3">
          {record.display_name || record.source_filename || 'Untitled video'}
        </h4>

        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>{getTimeAgo(record.createdAt)}</span>
            {record.completedAt && record.createdAt && (() => {
              const ms = new Date(record.completedAt!).getTime() - new Date(record.createdAt).getTime()
              const secs = Math.round(ms / 1000)
              return secs > 0 ? <><span className="text-muted-foreground/50">&middot;</span><span>{secs < 60 ? `${secs}s` : `${Math.round(secs / 60)}m`}</span></> : null
            })()}
            {record.usage?.cost_usd ? (
              <><span className="text-muted-foreground/50">&middot;</span><span>${record.usage.cost_usd.toFixed(3)}</span></>
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

export const ReframeLandingPage = () => (
  <LandingPageShell<ReframeRecord>
    title="Orientations"
    subtitle="Smart reframe 16:9 videos to 9:16 with AI subject tracking"
    icon={Smartphone}
    fetchRecords={() => api.reframe.list()}
    archiveRecord={(id) => api.reframe.archive(id)}
    createPath="/orientations/create"
    detailPath="/orientations"
    buttonLabel="New Reframe"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <ReframeCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No reframes yet"
    emptyDescription="Select a landscape video to intelligently reframe it to 9:16 portrait using AI subject tracking."
  />
)
