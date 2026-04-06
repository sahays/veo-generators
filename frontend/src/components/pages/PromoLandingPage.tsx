import { motion } from 'framer-motion'
import { Scissors, Archive } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'

const STATUS_STYLES: Record<string, string> = {
  pending: 'text-slate-600 bg-slate-500/10',
  analyzing: 'text-amber-600 bg-amber-500/10',
  extracting: 'text-blue-600 bg-blue-500/10',
  stitching: 'text-indigo-600 bg-indigo-500/10',
  encoding: 'text-purple-600 bg-purple-500/10',
  completed: 'text-emerald-600 bg-emerald-500/10',
  failed: 'text-red-600 bg-red-500/10',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  analyzing: 'Analyzing',
  extracting: 'Extracting',
  stitching: 'Stitching',
  encoding: 'Encoding',
  completed: 'Completed',
  failed: 'Failed',
}

interface PromoRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  usage?: { cost_usd?: number }
  prompt_name?: string
  createdAt: string
  completedAt?: string
}

const PromoCard = ({ record, onClick, onArchive, showArchive }: {
  record: PromoRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => (
  <motion.button
    key={record.id}
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    whileHover={{ y: -2 }}
    onClick={onClick}
    className="glass bg-card p-5 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
  >
    <div className="flex items-center gap-1.5 mb-1.5">
      <span className={cn(
        "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0",
        STATUS_STYLES[record.status] || STATUS_STYLES.pending
      )}>
        <Scissors size={10} />
        {STATUS_LABELS[record.status] || record.status}
      </span>
      {['analyzing', 'extracting', 'stitching', 'encoding'].includes(record.status) && (
        <span className="text-[9px] text-muted-foreground">{record.progress_pct}%</span>
      )}
    </div>

    <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-1">
      {record.display_name || record.source_filename || 'Untitled video'}
    </h4>
    {record.prompt_name && (
      <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-medium bg-amber-500/10 text-amber-600 mb-2">
        {record.prompt_name}
      </span>
    )}

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
  </motion.button>
)

export const PromoLandingPage = () => (
  <LandingPageShell<PromoRecord>
    title="Promos"
    subtitle="AI-powered promotional clips from your full-length videos"
    icon={Scissors}
    fetchRecords={() => api.promo.list()}
    archiveRecord={(id) => api.promo.archive(id)}
    createPath="/promos/create"
    detailPath="/promos"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <PromoCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No promos yet"
    emptyDescription="Select a video to generate a promotional highlight reel of the best moments."
  />
)
