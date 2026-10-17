import { useCallback, useRef, useState } from 'react'
import { AlertCircle, Loader2, Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

export const UploadZone = ({
  onUpload,
}: {
  onUpload: (files: File[]) => void
}) => {
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) onUpload(files)
    },
    [onUpload],
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

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
      onClick={() => inputRef.current?.click()}
      className={cn(
        'glass bg-card rounded-xl p-8 border-2 border-dashed transition-all duration-200 cursor-pointer text-center',
        isDragging
          ? 'border-accent bg-accent/5 scale-[1.01]'
          : 'border-border hover:border-accent/40',
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
        <div
          className={cn(
            'w-10 h-10 rounded-full flex items-center justify-center transition-colors',
            isDragging
              ? 'bg-accent/20 text-accent-dark'
              : 'bg-muted text-muted-foreground',
          )}
        >
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

export const UploadProgress = ({
  filename,
  progress,
  error,
}: {
  filename: string
  progress: number
  error?: string
}) => (
  <div
    className={cn(
      'glass rounded-lg p-3 flex items-center gap-3',
      error ? 'bg-red-500/10 border border-red-500/20' : 'bg-card',
    )}
  >
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
    {!error && (
      <span className="text-[10px] text-muted-foreground shrink-0">{progress}%</span>
    )}
  </div>
)
