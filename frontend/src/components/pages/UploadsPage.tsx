import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Loader2, Upload } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { cn } from '@/lib/utils'
import { UploadCard } from '@/components/pages/uploads/UploadCard'
import { UploadDetailView } from '@/components/pages/uploads/UploadDetailView'
import {
  UploadProgress,
  UploadZone,
} from '@/components/pages/uploads/UploadDropzone'
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

const UploadsLandingView = () => {
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [uploading, setUploading] = useState<
    { filename: string; progress: number; error?: string }[]
  >([])
  const [compressingMap, setCompressingMap] = useState<Record<string, string | null>>({})
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRecords = useCallback(async () => {
    try {
      setRecords(await api.uploads.list())
    } catch (err) {
      console.error('Failed to fetch uploads', err)
    }
  }, [])

  useEffect(() => {
    fetchRecords().finally(() => setIsLoading(false))
  }, [fetchRecords])

  // Poll compression status while any variant is processing.
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
          const hadProcessing = rec.compressed_variants.some((v) => v.status === 'processing')
          const allDone = result.variants.every(
            (v: CompressedVariant) => v.status !== 'processing',
          )
          if (hadProcessing && allDone) anyChanged = true
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
  }, [
    records.map((r) => r.id + r.compressed_variants.map((v) => v.status).join()).join(','),
    fetchRecords,
  ])

  const handleUpload = async (files: File[]) => {
    const entries = files.map((f) => ({ filename: f.name, progress: 0, error: '' }))
    setUploading((prev) => [...prev, ...entries])
    const baseIdx = uploading.length

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
              j === baseIdx + i
                ? { ...e, progress: -1, error: `Failed to upload ${file.name}` }
                : e,
            ),
          )
          throw err
        }
      }),
    )

    setTimeout(() => setUploading((prev) => prev.filter((e) => e.error)), 500)
    await fetchRecords()
  }

  const handleArchive = async (id: string) => {
    try {
      await api.uploads.archive(id)
      setRecords(records.filter((r) => r.id !== id))
    } catch (err) {
      console.error('Failed to archive upload', err)
    }
  }

  const handleCompress = async (recordId: string, resolution: string) => {
    setCompressingMap((prev) => ({ ...prev, [recordId]: resolution }))
    try {
      await api.uploads.compress(recordId, resolution)
      await fetchRecords()
    } catch (err) {
      console.error('Compression failed', err)
    } finally {
      setCompressingMap((prev) => ({ ...prev, [recordId]: null }))
    }
  }

  const filteredRecords =
    filter === 'all' ? records : records.filter((r) => r.file_type === filter)

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading files...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Files</h2>
          <p className="text-xs text-muted-foreground">
            {records.length} file{records.length !== 1 ? 's' : ''}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-medium transition-all',
              filter === f.value
                ? 'bg-accent text-slate-900'
                : 'bg-muted text-muted-foreground hover:bg-accent/10 hover:text-foreground',
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {isMaster && <UploadZone onUpload={handleUpload} />}

      {uploading.length > 0 && (
        <div className="space-y-2">
          {uploading.map((item, i) => (
            <UploadProgress
              key={i}
              filename={item.filename}
              progress={item.progress}
              error={item.error}
            />
          ))}
        </div>
      )}

      {filteredRecords.length === 0 && records.length === 0 ? (
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
            {isMaster
              ? 'Drag and drop files above or click to browse. Files can be used across all features.'
              : 'No files have been uploaded yet.'}
          </p>
        </motion.div>
      ) : filteredRecords.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-8">
          No {filter} files found
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredRecords.map((record) => (
            <UploadCard
              key={record.id}
              record={record}
              onClick={() => navigate(`/uploads/${record.id}`)}
              onArchive={(e) => {
                e.stopPropagation()
                handleArchive(record.id)
              }}
              onCompress={(res) => handleCompress(record.id, res)}
              compressingResolution={compressingMap[record.id]}
              canEdit={isMaster}
            />
          ))}
        </div>
      )}
    </div>
  )
}
