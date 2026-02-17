import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Image, Loader2, Archive, Upload, Film, Camera } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { useNavigate } from 'react-router-dom'
import type { ThumbnailRecord } from '@/types/project'

function getTimeAgo(timestamp: string | number): string {
  const ms = typeof timestamp === 'string' ? new Date(timestamp).getTime() : timestamp
  if (isNaN(ms)) return ''
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

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

const ThumbnailCard = ({
  record,
  onClick,
  onArchive,
}: {
  record: ThumbnailRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
}) => {
  return (
    <motion.button
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
            {record.video_filename || 'Untitled video'}
          </h4>
        </div>
        <span className={cn(
          "flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0",
          STATUS_STYLES[record.status] || STATUS_STYLES.analyzing
        )}>
          {record.status === 'completed' ? <Image size={10} /> : <Camera size={10} />}
          {STATUS_LABELS[record.status] || record.status}
        </span>
      </div>

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
        <button
          onClick={onArchive}
          className="p-1 -m-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
          title="Archive"
        >
          <Archive size={12} />
        </button>
      </div>
    </motion.button>
  )
}

export const ThumbnailsLandingPage = () => {
  const navigate = useNavigate()
  const [records, setRecords] = useState<ThumbnailRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    api.thumbnails.list()
      .then(setRecords)
      .catch((err) => console.error('Failed to fetch thumbnails', err))
      .finally(() => setIsLoading(false))
  }, [])

  const handleArchive = async (id: string) => {
    try {
      await api.thumbnails.archive(id)
      setRecords(records.filter(r => r.id !== id))
    } catch (err) {
      console.error('Failed to archive thumbnail', err)
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading thumbnails...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Thumbnails</h2>
          <p className="text-xs text-muted-foreground">
            {records.length} thumbnail{records.length !== 1 ? 's' : ''}
          </p>
        </div>
        <Button icon={Image} onClick={() => navigate('/thumbnails/create')}>Create Thumbnail</Button>
      </div>

      {records.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
        >
          <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
            <Image size={28} />
          </div>
          <h4 className="text-base font-heading font-bold text-foreground mb-1">No thumbnails yet</h4>
          <p className="text-sm text-muted-foreground max-w-xs mb-5">
            Upload a video or select a production to generate a YouTube-style thumbnail with AI.
          </p>
          <Button icon={Image} onClick={() => navigate('/thumbnails/create')}>Create Thumbnail</Button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {records.map((record) => (
            <ThumbnailCard
              key={record.id}
              record={record}
              onClick={() => navigate(`/thumbnails/${record.id}`)}
              onArchive={(e) => { e.stopPropagation(); handleArchive(record.id) }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
