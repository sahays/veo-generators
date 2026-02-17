import { useState, useEffect, useCallback, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Upload, Loader2, Archive, Video, Image as ImageIcon, File as FileIcon,
  ArrowLeft, Download, Shrink, CheckCircle2, XCircle, ExternalLink, AlertCircle
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useNavigate, useParams } from 'react-router-dom'
import type { UploadRecord, CompressedVariant } from '@/types/project'

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

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

const FILE_TYPE_ICONS: Record<string, typeof Video> = {
  video: Video,
  image: ImageIcon,
  other: FileIcon,
}

const FILE_TYPE_STYLES: Record<string, string> = {
  video: 'bg-purple-500/10 text-purple-600 border-purple-500/20',
  image: 'bg-blue-500/10 text-blue-600 border-blue-500/20',
  other: 'bg-gray-500/10 text-gray-600 border-gray-500/20',
}

// --- Upload Card ---
const UploadCard = ({
  record,
  onClick,
  onArchive,
  onCompress,
  compressingResolution,
}: {
  record: UploadRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  onCompress?: (resolution: string, e: React.MouseEvent) => void
  compressingResolution?: string | null
}) => {
  const TypeIcon = FILE_TYPE_ICONS[record.file_type] || FileIcon
  const isChild = !!record.parent_upload_id
  const resolutionBadge = record.resolution_label || (record.file_type === 'video' && !isChild ? 'original' : null)

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-4 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
    >
      {/* Row 1: Type + Resolution badges */}
      <div className="flex items-center gap-1.5 mb-2">
        <span className={cn(
          "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0",
          FILE_TYPE_STYLES[record.file_type] || FILE_TYPE_STYLES.other
        )}>
          <span className="flex items-center gap-1">
            <TypeIcon size={8} />
            {record.file_type}
          </span>
        </span>
        {resolutionBadge && (
          <span className={cn(
            "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0",
            isChild
              ? "bg-cyan-500/10 text-cyan-600 border-cyan-500/20"
              : "bg-gray-500/10 text-gray-500 border-gray-500/20"
          )}>
            {resolutionBadge}
          </span>
        )}
      </div>

      {/* Row 2: Filename */}
      <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-1">
        {record.filename}
      </h4>

      {/* Row 3: Size + time */}
      <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-3">
        <span>{formatFileSize(record.file_size_bytes)}</span>
        <span className="text-muted-foreground/50">&middot;</span>
        <span>{getTimeAgo(record.createdAt)}</span>
      </div>

      {/* Row 4: Inline compress actions (video originals only) */}
      {record.file_type === 'video' && !isChild && (
        <div className="flex items-center gap-2 mb-2">
          {(['480p', '720p'] as const).map((res) => {
            const existing = record.compressed_variants.find(v => v.resolution === res)
            const isProcessing = existing?.status === 'processing'
            const isSucceeded = existing?.status === 'succeeded'
            const isCompressingThis = compressingResolution === res

            return (
              <button
                key={res}
                onClick={(e) => {
                  e.stopPropagation()
                  if (!isProcessing && !isSucceeded && !isCompressingThis && onCompress) {
                    onCompress(res, e)
                  }
                }}
                disabled={isProcessing || isSucceeded || isCompressingThis}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all",
                  isSucceeded
                    ? "bg-emerald-500/10 text-emerald-600 cursor-default"
                    : isProcessing || isCompressingThis
                      ? "bg-amber-500/10 text-amber-600 cursor-wait"
                      : "bg-muted hover:bg-accent/10 hover:text-accent-dark text-foreground cursor-pointer"
                )}
              >
                {isCompressingThis || isProcessing ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : isSucceeded ? (
                  <CheckCircle2 size={10} />
                ) : (
                  <Shrink size={10} />
                )}
                {res}
              </button>
            )
          })}
        </div>
      )}

      {/* Row 5: Archive button */}
      <div className="flex items-center justify-end">
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

// --- Upload Zone ---
const UploadZone = ({ onUpload }: { onUpload: (files: File[]) => void }) => {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) onUpload(files)
  }, [onUpload])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleClick = () => inputRef.current?.click()

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length > 0) onUpload(files)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={handleClick}
      className={cn(
        "glass bg-card rounded-xl p-8 border-2 border-dashed transition-all duration-200 cursor-pointer text-center",
        isDragging
          ? "border-accent bg-accent/5 scale-[1.01]"
          : "border-border hover:border-accent/40"
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileChange}
        accept="video/*,image/*"
      />
      <div className="flex flex-col items-center gap-2">
        <div className={cn(
          "w-10 h-10 rounded-full flex items-center justify-center transition-colors",
          isDragging ? "bg-accent/20 text-accent-dark" : "bg-muted text-muted-foreground"
        )}>
          <Upload size={20} />
        </div>
        <p className="text-sm font-medium text-foreground">
          {isDragging ? 'Drop files here' : 'Drag & drop files or click to browse'}
        </p>
        <p className="text-xs text-muted-foreground">Videos and images supported</p>
      </div>
    </div>
  )
}

// --- Upload Progress Item ---
const UploadProgress = ({ filename, progress, error }: { filename: string; progress: number; error?: string }) => (
  <div className={cn("glass rounded-lg p-3 flex items-center gap-3", error ? "bg-red-500/10 border border-red-500/20" : "bg-card")}>
    {error ? (
      <AlertCircle size={14} className="text-red-500 shrink-0" />
    ) : (
      <Loader2 size={14} className="animate-spin text-accent shrink-0" />
    )}
    <div className="flex-1 min-w-0">
      <p className="text-xs font-medium text-foreground truncate">{filename}</p>
      {error ? (
        <p className="text-[10px] text-red-500 mt-0.5">{error}</p>
      ) : (
        <div className="mt-1 h-1 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-accent rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
    {!error && <span className="text-[10px] text-muted-foreground shrink-0">{progress}%</span>}
  </div>
)

// --- Detail View ---
const UploadDetailView = ({ id }: { id: string }) => {
  const navigate = useNavigate()
  const [record, setRecord] = useState<UploadRecord | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchRecord = useCallback(async () => {
    try {
      const data = await api.uploads.get(id)
      setRecord(data)
      return data
    } catch {
      console.error('Failed to fetch upload')
      return null
    }
  }, [id])

  useEffect(() => {
    fetchRecord().finally(() => setIsLoading(false))
  }, [fetchRecord])

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading file...</p>
      </div>
    )
  }

  if (!record) {
    return (
      <div className="text-center py-16">
        <p className="text-sm text-muted-foreground">File not found</p>
        <button onClick={() => navigate('/uploads')} className="text-accent text-sm mt-2 hover:underline">
          Back to files
        </button>
      </div>
    )
  }

  const TypeIcon = FILE_TYPE_ICONS[record.file_type] || FileIcon
  const isChild = !!record.parent_upload_id

  return (
    <div className="space-y-6">
      {/* Back link */}
      <button
        onClick={() => navigate('/uploads')}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft size={14} />
        Back to files
      </button>

      {/* File preview */}
      {record.signed_url && (
        <div className="glass bg-card rounded-xl overflow-hidden border border-border">
          {record.file_type === 'video' ? (
            <video
              src={record.signed_url}
              controls
              className="w-full max-h-[400px] bg-black"
            />
          ) : record.file_type === 'image' ? (
            <img
              src={record.signed_url}
              alt={record.filename}
              className="w-full max-h-[400px] object-contain bg-black"
            />
          ) : null}
        </div>
      )}

      {/* File metadata */}
      <div className="glass bg-card rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2">
          <span className={cn(
            "px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border",
            FILE_TYPE_STYLES[record.file_type] || FILE_TYPE_STYLES.other
          )}>
            <span className="flex items-center gap-1">
              <TypeIcon size={10} />
              {record.file_type}
            </span>
          </span>
          {record.resolution_label && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border bg-cyan-500/10 text-cyan-600 border-cyan-500/20">
              {record.resolution_label}
            </span>
          )}
          {record.file_type === 'video' && !isChild && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border bg-gray-500/10 text-gray-500 border-gray-500/20">
              original
            </span>
          )}
          <h3 className="text-base font-heading font-bold text-foreground">{record.filename}</h3>
        </div>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <span className="text-muted-foreground">MIME type</span>
            <p className="font-medium text-foreground">{record.mime_type}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Size</span>
            <p className="font-medium text-foreground">{formatFileSize(record.file_size_bytes)}</p>
          </div>
          <div>
            <span className="text-muted-foreground">Uploaded</span>
            <p className="font-medium text-foreground">{getTimeAgo(record.createdAt)}</p>
          </div>
          {isChild && (
            <div>
              <span className="text-muted-foreground">Source</span>
              <button
                onClick={() => navigate(`/uploads/${record.parent_upload_id}`)}
                className="flex items-center gap-1 font-medium text-accent hover:text-accent-dark transition-colors"
              >
                View original
                <ExternalLink size={10} />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Compressed variants download links (originals only) */}
      {record.compressed_variants.length > 0 && (
        <div className="glass bg-card rounded-xl p-5 space-y-3">
          <h4 className="text-sm font-heading font-bold text-foreground">Compressed Variants</h4>
          <div className="space-y-2">
            {record.compressed_variants.map((v, i) => (
              <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium",
                    v.status === 'succeeded' ? 'text-emerald-600 bg-emerald-500/10'
                      : v.status === 'processing' ? 'text-amber-600 bg-amber-500/10'
                        : v.status === 'failed' ? 'text-red-600 bg-red-500/10'
                          : 'text-gray-500 bg-gray-500/10'
                  )}>
                    {v.status === 'processing' && <Loader2 size={9} className="animate-spin" />}
                    {v.status === 'succeeded' && <CheckCircle2 size={9} />}
                    {v.status === 'failed' && <XCircle size={9} />}
                    {v.status}
                  </span>
                  <span className="text-xs font-medium text-foreground">{v.resolution}</span>
                </div>
                <div className="flex items-center gap-3">
                  {v.child_upload_id && (
                    <button
                      onClick={() => navigate(`/uploads/${v.child_upload_id}`)}
                      className="flex items-center gap-1 text-xs text-accent hover:text-accent-dark transition-colors"
                    >
                      <ExternalLink size={12} />
                      View record
                    </button>
                  )}
                  {v.status === 'succeeded' && v.signed_url && (
                    <a
                      href={v.signed_url}
                      download
                      className="flex items-center gap-1 text-xs text-accent hover:text-accent-dark transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Download size={12} />
                      Download
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// --- Main Page ---
export const UploadsPage = () => {
  const { id } = useParams<{ id: string }>()

  if (id) {
    return <UploadDetailView id={id} />
  }

  return <UploadsLandingView />
}

type FilterType = 'all' | 'video' | 'image'

const UploadsLandingView = () => {
  const navigate = useNavigate()
  const [records, setRecords] = useState<UploadRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [uploading, setUploading] = useState<{ filename: string; progress: number; error?: string }[]>([])
  const [compressingMap, setCompressingMap] = useState<Record<string, string | null>>({})
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchRecords = useCallback(async () => {
    try {
      const data = await api.uploads.list()
      setRecords(data)
    } catch (err) {
      console.error('Failed to fetch uploads', err)
    }
  }, [])

  useEffect(() => {
    fetchRecords().finally(() => setIsLoading(false))
  }, [fetchRecords])

  // Poll compression status for any record with processing variants
  useEffect(() => {
    const processingRecords = records.filter(r =>
      r.compressed_variants.some(v => v.status === 'processing')
    )

    if (processingRecords.length === 0) {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
      return
    }

    if (pollRef.current) return // already polling

    pollRef.current = setInterval(async () => {
      let anyChanged = false
      for (const rec of processingRecords) {
        try {
          const result = await api.uploads.compressStatus(rec.id)
          const hadProcessing = rec.compressed_variants.some(v => v.status === 'processing')
          const allDone = result.variants.every((v: CompressedVariant) => v.status !== 'processing')
          if (hadProcessing && allDone) anyChanged = true
        } catch {
          // ignore
        }
      }
      if (anyChanged) {
        // Refresh full list to pick up new child records
        await fetchRecords()
      }
    }, 5000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [records.map(r => r.id + r.compressed_variants.map(v => v.status).join()).join(','), fetchRecords])

  const handleUpload = async (files: File[]) => {
    const entries = files.map(f => ({ filename: f.name, progress: 0, error: '' }))
    setUploading(prev => [...prev, ...entries])
    const baseIdx = uploading.length

    const results = await Promise.allSettled(
      files.map(async (file, i) => {
        setUploading(prev => prev.map((e, j) =>
          j === baseIdx + i ? { ...e, progress: 30 } : e
        ))
        try {
          const result = await api.assets.upload(file)
          setUploading(prev => prev.map((e, j) =>
            j === baseIdx + i ? { ...e, progress: 100 } : e
          ))
          return result
        } catch (err) {
          setUploading(prev => prev.map((e, j) =>
            j === baseIdx + i ? { ...e, progress: -1, error: `Failed to upload ${file.name}` } : e
          ))
          throw err
        }
      })
    )

    const failures = results.filter(r => r.status === 'rejected')
    if (failures.length > 0) {
      console.error(`${failures.length} upload(s) failed`)
    }

    setTimeout(() => {
      setUploading(prev => prev.filter(e => e.error))
    }, 500)
    await fetchRecords()
  }

  const handleArchive = async (id: string) => {
    try {
      await api.uploads.archive(id)
      setRecords(records.filter(r => r.id !== id))
    } catch (err) {
      console.error('Failed to archive upload', err)
    }
  }

  const handleCompress = async (recordId: string, resolution: string) => {
    setCompressingMap(prev => ({ ...prev, [recordId]: resolution }))
    try {
      await api.uploads.compress(recordId, resolution)
      await fetchRecords()
    } catch (err) {
      console.error('Compression failed', err)
    } finally {
      setCompressingMap(prev => ({ ...prev, [recordId]: null }))
    }
  }

  const filteredRecords = filter === 'all'
    ? records
    : records.filter(r => r.file_type === filter)

  const filters: { label: string; value: FilterType }[] = [
    { label: 'All', value: 'all' },
    { label: 'Videos', value: 'video' },
    { label: 'Images', value: 'image' },
  ]

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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Files</h2>
          <p className="text-xs text-muted-foreground">
            {records.length} file{records.length !== 1 ? 's' : ''}
          </p>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-2">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium transition-all",
              filter === f.value
                ? "bg-accent text-slate-900"
                : "bg-muted text-muted-foreground hover:bg-accent/10 hover:text-foreground"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Upload zone */}
      <UploadZone onUpload={handleUpload} />

      {/* Upload progress */}
      {uploading.length > 0 && (
        <div className="space-y-2">
          {uploading.map((item, i) => (
            <UploadProgress key={i} filename={item.filename} progress={item.progress} error={item.error} />
          ))}
        </div>
      )}

      {/* File grid */}
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
            Drag and drop files above or click to browse. Files can be used across all features.
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
              onArchive={(e) => { e.stopPropagation(); handleArchive(record.id) }}
              onCompress={(res) => handleCompress(record.id, res)}
              compressingResolution={compressingMap[record.id]}
            />
          ))}
        </div>
      )}
    </div>
  )
}
