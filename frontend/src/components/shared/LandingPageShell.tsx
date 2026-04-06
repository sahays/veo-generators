import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Loader2, type LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/Common'
import { useAuthStore } from '@/store/useAuthStore'

interface LandingPageShellProps<T> {
  title: string
  subtitle: string | ((count: number) => string)
  icon: LucideIcon
  fetchRecords: () => Promise<T[]>
  archiveRecord: (id: string) => Promise<unknown>
  createPath: string
  detailPath: string
  renderCard: (record: T, onClick: () => void, onArchive: (e: React.MouseEvent) => void, showArchive: boolean) => React.ReactNode
  emptyTitle: string
  emptyDescription: string
  buttonLabel?: string
  gridClassName?: string
}

export const LandingPageShell = <T extends { id: string }>({
  title,
  subtitle,
  icon: Icon,
  fetchRecords,
  archiveRecord,
  createPath,
  detailPath,
  renderCard,
  emptyTitle,
  emptyDescription,
  buttonLabel,
  gridClassName = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4',
}: LandingPageShellProps<T>) => {
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()
  const [records, setRecords] = useState<T[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchRecords()
      .then(setRecords)
      .catch((err) => console.error(`Failed to fetch ${title.toLowerCase()}`, err))
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleArchive = async (id: string) => {
    try {
      await archiveRecord(id)
      setRecords((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      console.error(`Failed to archive ${title.toLowerCase()} record`, err)
    }
  }

  const btnLabel = buttonLabel ?? `New ${title.replace(/s$/, '')}`
  const resolvedSubtitle = typeof subtitle === 'function' ? subtitle(records.length) : subtitle

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">{title}</h2>
          <p className="text-xs text-muted-foreground">{resolvedSubtitle}</p>
        </div>
        {isMaster && (
          <Button icon={Icon} onClick={() => navigate(createPath)}>
            {btnLabel}
          </Button>
        )}
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-32 space-y-4">
          <Loader2 className="animate-spin text-accent" size={32} />
          <p className="text-sm text-muted-foreground">Loading {title.toLowerCase()}...</p>
        </div>
      ) : records.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
        >
          <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
            <Icon size={28} />
          </div>
          <h4 className="text-base font-heading font-bold text-foreground mb-1">{emptyTitle}</h4>
          <p className="text-sm text-muted-foreground max-w-xs mb-5">{emptyDescription}</p>
          {isMaster && (
            <Button icon={Icon} onClick={() => navigate(createPath)}>
              {btnLabel}
            </Button>
          )}
        </motion.div>
      ) : (
        <div className={gridClassName}>
          {records.map((record) =>
            renderCard(
              record,
              () => navigate(`${detailPath}/${record.id}`),
              (e) => { e.stopPropagation(); handleArchive(record.id) },
              isMaster,
            )
          )}
        </div>
      )}
    </div>
  )
}
