import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Loader2, Upload } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { api } from '@/hooks/useApiClient'
import { useAuthStore } from '@/store/useAuthStore'
import { ShowMore } from '@/components/shared/ShowMore'
import { useShowMore } from '@/hooks/useShowMore'
import { UploadCard } from '@/components/pages/uploads/components/UploadCard'
import { UploadDetailView } from '@/components/pages/uploads/components/UploadDetailView'
import {
  UploadProgress,
  UploadZone,
} from '@/components/pages/uploads/components/UploadDropzone'
import type { CompressedVariant, UploadRecord } from '@/types/project'

type FilterType = 'all' | 'video' | 'image'

const FILTERS: { label: string; value: FilterType }[] = [
  { label: 'All', value: 'all' },
  { label: 'Videos', value: 'video' },
  { label: 'Images', value: 'image' },
]

export const UploadsPage = () => {
  const { id } = useParams<{ id: string }>()
  return id ? <UploadDetailView id={id} /> : <UploadsLandingView />
}

function useCompressionPoller(records: UploadRecord[], fetchRecords: () => Promise<void>) {
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const statusKey = records
    .map((r) => r.id + r.compressed_variants.map((v) => v.status).join())
    .join(',')

  useEffect(() => {
    const processing = records.filter((r) =>
      r.compressed_variants.some((v) => v.status === 'processing'),
    )
    if (processing.length === 0) {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
      return
    }
    if (pollRef.current) return

    pollRef.current = setInterval(async () => {
      let anyChanged = false
      for (const rec of processing) {
        try {
          const result = await api.uploads.compressStatus(rec.id)
          const allDone = result.variants.every((v: CompressedVariant) => v.status !== 'processing')
          if (allDone) anyChanged = true
        } catch {
          // ignore
        }
      }
      if (anyChanged) await fetchRecords()
    }, 5000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusKey, fetchRecords])
}

function useUploadsData() {
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [uploading, setUploading] = useState<{ filename: string; progress: number; error?: string }[]>([])
  const [compressingMap, setCompressingMap] = useState<Record<string, string | null>>({})

  const fetchRecords = useCallback(async () => {
    try { setRecords(await api.uploads.list()) } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchRecords().finally(() => setIsLoading(false)) }, [fetchRecords])
  useCompressionPoller(records, fetchRecords)

  const handleArchive = async (id: string) => {
    try { await api.uploads.archive(id); setRecords((prev) => prev.filter((r) => r.id !== id)) } catch { /* ignore */ }
  }
  const handleCompress = async (recordId: string, resolution: string) => {
    setCompressingMap((prev) => ({ ...prev, [recordId]: resolution }))
    try { await api.uploads.compress(recordId, resolution); await fetchRecords() } catch { /* ignore */ } finally {
      setCompressingMap((prev) => ({ ...prev, [recordId]: null }))
    }
  }
  return { records, isLoading, uploading, setUploading, compressingMap, fetchRecords, handleArchive, handleCompress }
}

async function runBatchUpload(
  files: File[],
  baseIdx: number,
  setUploading: React.Dispatch<React.SetStateAction<{ filename: string; progress: number; error?: string }[]>>,
  fetchRecords: () => Promise<void>,
) {
  const entries = files.map((f) => ({ filename: f.name, progress: 0, error: '' }))
  setUploading((prev) => [...prev, ...entries])

  await Promise.allSettled(
    files.map(async (file, i) => {
      try {
        const { promise } = api.assets.directUpload(file, (pct) => {
          setUploading((prev) =>
            prev.map((e, j) => (j === baseIdx + i ? { ...e, progress: pct } : e)),
          )
        })
        return await promise
      } catch (err) {
        setUploading((prev) =>
          prev.map((e, j) =>
            j === baseIdx + i ? { ...e, progress: -1, error: `Failed to upload ${file.name}` } : e,
          ),
        )
        throw err
      }
    }),
  )

  setTimeout(() => setUploading((prev) => prev.filter((e) => e.error)), 500)
  await fetchRecords()
}

const EmptyUploadsCard = ({ canWrite }: { canWrite: boolean }) => (
  <motion.div
    initial={{ opacity: 0 }}
    animate={{ opacity: 1 }}
    className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
  >
    <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
      <Upload size={28} />
    </div>
    <h4 className="text-base font-heading font-bold text-foreground mb-1">No files yet</h4>
    <p className="text-sm text-muted-foreground max-w-xs">
      {canWrite
        ? 'Drag and drop files above or click to browse. Files can be used across all features.'
        : 'No files have been uploaded yet.'}
    </p>
  </motion.div>
)

const UploadsGridSection = ({
  records,
  filteredRecords,
  filter,
  canWrite,
  compressingMap,
  onOpen,
  onArchive,
  onCompress,
}: {
  records: UploadRecord[]
  filteredRecords: UploadRecord[]
  filter: FilterType
  canWrite: boolean
  compressingMap: Record<string, string | null>
  onOpen: (id: string) => void
  onArchive: (id: string) => void
  onCompress: (id: string, res: string) => void
}) => {
  const { visible, hasMore, remaining, showMore } = useShowMore(filteredRecords, 10)

  if (filteredRecords.length === 0 && records.length === 0) {
    return <EmptyUploadsCard canWrite={canWrite} />
  }
  if (filteredRecords.length === 0) {
    return <p className="text-sm text-muted-foreground text-center py-8">No {filter} files found</p>
  }
  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {visible.map((record) => (
          <UploadCard
            key={record.id}
            record={record}
            onClick={() => onOpen(record.id)}
            onArchive={(e) => {
              e.stopPropagation()
              onArchive(record.id)
            }}
            onCompress={(res) => onCompress(record.id, res)}
            compressingResolution={compressingMap[record.id]}
            canEdit={canWrite}
          />
        ))}
      </div>
      <ShowMore hasMore={hasMore} remaining={remaining} onClick={showMore} />
    </>
  )
}

const UploadsHeaderAndFilters = ({ count, filter, setFilter }: { count: number; filter: FilterType; setFilter: (f: FilterType) => void }) => (
  <>
    <div className="space-y-1">
      <h2 className="text-xl font-heading text-foreground tracking-tight">Files</h2>
      <p className="text-xs text-muted-foreground">{count} file{count !== 1 ? 's' : ''}</p>
    </div>
    <div className="flex items-center gap-2">
      {FILTERS.map((f) => (
        <Button key={f.value} variant={filter === f.value ? 'primary' : 'secondary'} size="sm" onClick={() => setFilter(f.value)}>
          {f.label}
        </Button>
      ))}
    </div>
  </>
)

const UploadsLandingView = () => {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [filter, setFilter] = useState<FilterType>('all')
  const data = useUploadsData()

  if (data.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading files...</p>
      </div>
    )
  }

  const filteredRecords = filter === 'all' ? data.records : data.records.filter((r) => r.file_type === filter)
  return (
    <div className="space-y-6">
      <UploadsHeaderAndFilters count={data.records.length} filter={filter} setFilter={setFilter} />
      {canWrite && <UploadZone onUpload={(files) => runBatchUpload(files, data.uploading.length, data.setUploading, data.fetchRecords)} />}
      {data.uploading.length > 0 && (
        <div className="space-y-2">
          {data.uploading.map((item, i) => <UploadProgress key={i} filename={item.filename} progress={item.progress} error={item.error} />)}
        </div>
      )}
      <UploadsGridSection records={data.records} filteredRecords={filteredRecords} filter={filter} canWrite={canWrite} compressingMap={data.compressingMap} onOpen={(id) => navigate(`/uploads/${id}`)} onArchive={data.handleArchive} onCompress={data.handleCompress} />
    </div>
  )
}
