import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Smartphone, Loader2, Archive } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/useAuthStore'

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
  status: string
  progress_pct: number
  source_signed_url?: string
  output_signed_url?: string
  usage?: { cost_usd?: number }
  createdAt: string
  completedAt?: string
}

const ReframeCard = ({
  record,
  onClick,
  onArchive,
  showArchive,
}: {
  record: ReframeRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => {
  return (
    <motion.button
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
          <Smartphone size={10} />
          {STATUS_LABELS[record.status] || record.status}
        </span>
        {record.status === 'processing' || record.status === 'encoding' || record.status === 'analyzing' ? (
          <span className="text-[9px] text-muted-foreground">{record.progress_pct}%</span>
        ) : null}
      </div>

      <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-3">
        {record.source_filename || 'Untitled video'}
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
    </motion.button>
  )
}

export const ReframeLandingPage = () => {
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()
  const [records, setRecords] = useState<ReframeRecord[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.reframe.list()
      .then(setRecords)
      .catch((err) => console.error('Failed to fetch reframes', err))
      .finally(() => setLoading(false))
  }, [])

  const handleArchive = async (id: string) => {
    try {
      await api.reframe.archive(id)
      setRecords(records.filter(r => r.id !== id))
    } catch (err) {
      console.error('Failed to archive reframe', err)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Orientations</h2>
          <p className="text-xs text-muted-foreground">
            Smart reframe 16:9 videos to 9:16 with AI subject tracking
          </p>
        </div>
        {isMaster && <Button icon={Smartphone} onClick={() => navigate('/orientations/create')}>New Reframe</Button>}
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-32 space-y-4">
          <Loader2 className="animate-spin text-accent" size={32} />
          <p className="text-sm text-muted-foreground">Loading reframes...</p>
        </div>
      ) : records.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
        >
          <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
            <Smartphone size={28} />
          </div>
          <h4 className="text-base font-heading font-bold text-foreground mb-1">No reframes yet</h4>
          <p className="text-sm text-muted-foreground max-w-xs mb-5">
            Select a landscape video to intelligently reframe it to 9:16 portrait using AI subject tracking.
          </p>
          {isMaster && <Button icon={Smartphone} onClick={() => navigate('/orientations/create')}>New Reframe</Button>}
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {records.map((record) => (
            <ReframeCard
              key={record.id}
              record={record}
              onClick={() => navigate(`/orientations/${record.id}`)}
              onArchive={(e) => { e.stopPropagation(); handleArchive(record.id) }}
              showArchive={isMaster}
            />
          ))}
        </div>
      )}
    </div>
  )
}
