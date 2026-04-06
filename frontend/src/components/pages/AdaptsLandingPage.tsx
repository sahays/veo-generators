import { motion } from 'framer-motion'
import { LayoutGrid, Archive } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import type { AdaptRecord } from '@/types/project'

const STATUS_STYLES: Record<string, string> = {
  pending: 'text-slate-600 bg-slate-500/10',
  generating: 'text-amber-600 bg-amber-500/10',
  completed: 'text-emerald-600 bg-emerald-500/10',
  partial: 'text-orange-600 bg-orange-500/10',
  failed: 'text-red-600 bg-red-500/10',
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  generating: 'Generating',
  completed: 'Completed',
  partial: 'Partial',
  failed: 'Failed',
}

const AdaptCard = ({ record, onClick, onArchive, showArchive }: {
  record: AdaptRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => {
  const completedCount = record.variants.filter(v => v.status === 'completed').length
  const totalCount = record.variants.length

  return (
    <motion.button
      key={record.id}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full overflow-hidden"
    >
      {record.source_signed_url && (
        <div className="aspect-video bg-muted/50 overflow-hidden">
          <img
            src={record.source_signed_url}
            alt={record.display_name || record.source_filename}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <div className="p-4">
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className={cn(
            "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0",
            STATUS_STYLES[record.status] || STATUS_STYLES.pending
          )}>
            <LayoutGrid size={10} />
            {STATUS_LABELS[record.status] || record.status}
          </span>
          {['generating'].includes(record.status) && (
            <span className="text-[9px] text-muted-foreground">{record.progress_pct}%</span>
          )}
          <span className="text-[9px] text-muted-foreground ml-auto">
            {completedCount}/{totalCount} variants
          </span>
        </div>

        <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-1">
          {record.display_name || record.source_filename || 'Untitled adapt'}
        </h4>

        {record.preset_bundle && (
          <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-medium bg-amber-500/10 text-amber-600 mb-2 capitalize">
            {record.preset_bundle}
          </span>
        )}

        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>{getTimeAgo(record.createdAt)}</span>
            {record.completedAt && record.createdAt && (() => {
              const ms = new Date(record.completedAt).getTime() - new Date(record.createdAt).getTime()
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

export const AdaptsLandingPage = () => (
  <LandingPageShell<AdaptRecord>
    title="Adapts"
    subtitle="Generate image variants across multiple aspect ratios for different devices and platforms"
    icon={LayoutGrid}
    fetchRecords={() => api.adapts.list()}
    archiveRecord={(id) => api.adapts.archive(id)}
    createPath="/adapts/create"
    detailPath="/adapts"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <AdaptCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No adapts yet"
    emptyDescription="Select an image to generate adapted versions for multiple aspect ratios and form factors."
  />
)
