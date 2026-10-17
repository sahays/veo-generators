import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Loader2, type LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/Common'
import { ShowMore } from '@/components/shared/ShowMore'
import { useShowMore } from '@/hooks/useShowMore'
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

const LandingEmptyState = ({
  icon: Icon,
  emptyTitle,
  emptyDescription,
  canWrite,
  btnLabel,
  onCreate,
}: {
  icon: LucideIcon
  emptyTitle: string
  emptyDescription: string
  canWrite: boolean
  btnLabel: string
  onCreate: () => void
}) => (
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
    {canWrite && (
      <Button icon={Icon} onClick={onCreate}>
        {btnLabel}
      </Button>
    )}
  </motion.div>
)

const LandingHeader = ({
  title,
  subtitle,
  canWrite,
  icon,
  btnLabel,
  onCreate,
}: {
  title: string
  subtitle: string
  canWrite: boolean
  icon: LucideIcon
  btnLabel: string
  onCreate: () => void
}) => (
  <div className="flex items-center justify-between">
    <div className="space-y-1">
      <h2 className="text-xl font-heading text-foreground tracking-tight">{title}</h2>
      <p className="text-xs text-muted-foreground">{subtitle}</p>
    </div>
    {canWrite && (
      <Button icon={icon} onClick={onCreate}>
        {btnLabel}
      </Button>
    )}
  </div>
)

const LandingBody = <T extends { id: string }>({
  loading,
  title,
  records,
  visible,
  hasMore,
  remaining,
  showMore,
  gridClassName,
  detailPath,
  canWrite,
  renderCard,
  handleArchive,
  emptyState,
}: {
  loading: boolean
  title: string
  records: T[]
  visible: T[]
  hasMore: boolean
  remaining: number
  showMore: () => void
  gridClassName: string
  detailPath: string
  canWrite: boolean
  renderCard: LandingPageShellProps<T>['renderCard']
  handleArchive: (id: string) => void
  emptyState: React.ReactNode
}) => {
  const navigate = useNavigate()
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading {title.toLowerCase()}...</p>
      </div>
    )
  }
  if (records.length === 0) return <>{emptyState}</>
  return (
    <>
      <div className={gridClassName}>
        {visible.map((record) => renderCard(record, () => navigate(`${detailPath}/${record.id}`), (e) => { e.stopPropagation(); handleArchive(record.id) }, canWrite))}
      </div>
      <ShowMore hasMore={hasMore} remaining={remaining} onClick={showMore} />
    </>
  )
}

export const LandingPageShell = <T extends { id: string }>(props: LandingPageShellProps<T>) => {
  const { title, subtitle, icon: Icon, fetchRecords, archiveRecord, createPath, detailPath, renderCard, emptyTitle, emptyDescription, buttonLabel, gridClassName = 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4' } = props
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [records, setRecords] = useState<T[]>([])
  const [loading, setLoading] = useState(true)
  const { visible, hasMore, remaining, showMore } = useShowMore(records, 10)

  useEffect(() => {
    fetchRecords().then(setRecords).catch(() => undefined).finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleArchive = async (id: string) => {
    try { await archiveRecord(id); setRecords((prev) => prev.filter((r) => r.id !== id)) } catch { return }
  }

  const btnLabel = buttonLabel ?? `New ${title.replace(/s$/, '')}`
  const resolvedSubtitle = typeof subtitle === 'function' ? subtitle(records.length) : subtitle

  return (
    <div className="space-y-6">
      <LandingHeader title={title} subtitle={resolvedSubtitle} canWrite={canWrite} icon={Icon} btnLabel={btnLabel} onCreate={() => navigate(createPath)} />
      <LandingBody loading={loading} title={title} records={records} visible={visible} hasMore={hasMore} remaining={remaining} showMore={showMore} gridClassName={gridClassName} detailPath={detailPath} canWrite={canWrite} renderCard={renderCard} handleArchive={handleArchive} emptyState={<LandingEmptyState icon={Icon} emptyTitle={emptyTitle} emptyDescription={emptyDescription} canWrite={canWrite} btnLabel={btnLabel} onCreate={() => navigate(createPath)} />} />
    </div>
  )
}
