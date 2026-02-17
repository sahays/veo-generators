import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Zap, Loader2, Clock, Tag, Archive, Upload, Film } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { useNavigate } from 'react-router-dom'
import type { KeyMomentsRecord } from '@/types/project'

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

const AnalysisCard = ({
  record,
  onClick,
  onArchive,
}: {
  record: KeyMomentsRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
}) => {
  const firstMoment = record.key_moments?.[0]

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

export const KeyMomentsLandingPage = () => {
  const navigate = useNavigate()
  const [records, setRecords] = useState<KeyMomentsRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    api.keyMoments.list()
      .then(setRecords)
      .catch((err) => console.error('Failed to fetch key moments', err))
      .finally(() => setIsLoading(false))
  }, [])

  const handleArchive = async (id: string) => {
    try {
      await api.keyMoments.archive(id)
      setRecords(records.filter(r => r.id !== id))
    } catch (err) {
      console.error('Failed to archive analysis', err)
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading analyses...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Key Moments</h2>
          <p className="text-xs text-muted-foreground">
            {records.length} analysis{records.length !== 1 ? 'es' : ''}
          </p>
        </div>
        <Button icon={Zap} onClick={() => navigate('/key-moments/analyze')}>Find Key Moments</Button>
      </div>

      {records.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
        >
          <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
            <Zap size={28} />
          </div>
          <h4 className="text-base font-heading font-bold text-foreground mb-1">No analyses yet</h4>
          <p className="text-sm text-muted-foreground max-w-xs mb-5">
            Upload a video or select a production to discover key moments with AI.
          </p>
          <Button icon={Zap} onClick={() => navigate('/key-moments/analyze')}>Find Key Moments</Button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {records.map((record) => (
            <AnalysisCard
              key={record.id}
              record={record}
              onClick={() => navigate(`/key-moments/${record.id}`)}
              onArchive={(e) => { e.stopPropagation(); handleArchive(record.id) }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
