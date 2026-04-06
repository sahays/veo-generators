import { motion } from 'framer-motion'
import { Zap, Clock, Tag, Archive, Upload, Film } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import type { KeyMomentsRecord } from '@/types/project'

const AnalysisCard = ({ record, onClick, onArchive, showArchive }: {
  record: KeyMomentsRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => {
  const firstMoment = record.key_moments?.[0]

  return (
    <motion.button
      key={record.id}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-5 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={cn(
            "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border",
            record.video_source === 'production'
              ? "bg-indigo-500/10 text-indigo-600 border-indigo-500/20"
              : "bg-accent/10 text-accent-dark border-accent/20"
          )}>
            {record.video_source === 'production' ? (
              <span className="flex items-center gap-1"><Film size={8} /> Production</span>
            ) : (
              <span className="flex items-center gap-1"><Upload size={8} /> Upload</span>
            )}
          </span>
          <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1">
            {record.display_name || record.video_filename || 'Untitled video'}
          </h4>
        </div>
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0 text-emerald-600 bg-emerald-500/10">
          <Clock size={10} />
          {record.moment_count} moment{record.moment_count !== 1 ? 's' : ''}
        </span>
      </div>

      {record.video_summary && (
        <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">
          {record.video_summary}
        </p>
      )}

      {firstMoment?.tags && firstMoment.tags.length > 0 && (
        <div className="flex items-center gap-1 mb-3 flex-wrap">
          <Tag size={10} className="text-muted-foreground shrink-0" />
          {firstMoment.tags.slice(0, 4).map((tag, j) => (
            <span key={j} className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
              {tag}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{getTimeAgo(record.createdAt)}</span>
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
}

export const KeyMomentsLandingPage = () => (
  <LandingPageShell<KeyMomentsRecord>
    title="Key Moments"
    subtitle={(count) => `${count} analysis${count !== 1 ? 'es' : ''}`}
    icon={Zap}
    fetchRecords={() => api.keyMoments.list()}
    archiveRecord={(id) => api.keyMoments.archive(id)}
    createPath="/key-moments/analyze"
    detailPath="/key-moments"
    buttonLabel="Find Key Moments"
    gridClassName="grid grid-cols-1 gap-4"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <AnalysisCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No analyses yet"
    emptyDescription="Upload a video or select a production to discover key moments with AI."
  />
)
