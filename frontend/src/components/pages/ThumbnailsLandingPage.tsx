import { motion } from 'framer-motion'
import { Image, Archive, Upload, Film, Camera } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import type { ThumbnailRecord } from '@/types/project'

const STATUS_STYLES: Record<string, string> = {
  analyzing: 'text-amber-600 bg-amber-500/10',
  screenshots_ready: 'text-blue-600 bg-blue-500/10',
  generating: 'text-purple-600 bg-purple-500/10',
  completed: 'text-emerald-600 bg-emerald-500/10',
}

const STATUS_LABELS: Record<string, string> = {
  analyzing: 'Analyzing',
  screenshots_ready: 'Ready',
  generating: 'Generating',
  completed: 'Completed',
}

const ThumbnailCard = ({ record, onClick, onArchive, showArchive }: {
  record: ThumbnailRecord
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
        "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0",
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
      <span className={cn(
        "flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-medium shrink-0",
        STATUS_STYLES[record.status] || STATUS_STYLES.analyzing
      )}>
        {record.status === 'completed' ? <Image size={10} /> : <Camera size={10} />}
        {STATUS_LABELS[record.status] || record.status}
      </span>
    </div>

    <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-2">
      {record.display_name || record.video_filename || 'Untitled video'}
    </h4>

    {record.thumbnail_signed_url && (
      <div className="mb-3 rounded-lg overflow-hidden border border-border aspect-video bg-black">
        <img
          src={record.thumbnail_signed_url}
          alt="Generated thumbnail"
          className="w-full h-full object-cover"
        />
      </div>
    )}

    {record.video_summary && (
      <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">
        {record.video_summary}
      </p>
    )}

    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
      <div className="flex items-center gap-2">
        <span>{getTimeAgo(record.createdAt)}</span>
        <span className="text-muted-foreground/50">·</span>
        <span>{record.screenshots.length} screenshot{record.screenshots.length !== 1 ? 's' : ''}</span>
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

export const ThumbnailsLandingPage = () => (
  <LandingPageShell<ThumbnailRecord>
    title="Thumbnails"
    subtitle={(count) => `${count} thumbnail${count !== 1 ? 's' : ''}`}
    icon={Image}
    fetchRecords={() => api.thumbnails.list()}
    archiveRecord={(id) => api.thumbnails.archive(id)}
    createPath="/thumbnails/create"
    detailPath="/thumbnails"
    buttonLabel="Create Thumbnail"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <ThumbnailCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No thumbnails yet"
    emptyDescription="Upload a video or select a production to generate a YouTube-style thumbnail with AI."
  />
)
