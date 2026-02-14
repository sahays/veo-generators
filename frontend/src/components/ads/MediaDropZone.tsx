import { useState, useRef, useCallback, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, X, Film, Image as ImageIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { MediaFile } from '@/types/project'

interface MediaDropZoneProps {
  files: MediaFile[]
  onChange: (files: MediaFile[]) => void
}

export const MediaDropZone = ({ files, onChange }: MediaDropZoneProps) => {
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounter = useRef(0)

  useEffect(() => {
    return () => {
      files.forEach((f) => URL.revokeObjectURL(f.previewUrl))
    }
  // only on unmount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const processFiles = useCallback(
    (fileList: FileList) => {
      const newFiles: MediaFile[] = Array.from(fileList)
        .filter((f) => f.type.startsWith('image/') || f.type.startsWith('video/'))
        .map((file) => ({
          id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          file,
          previewUrl: URL.createObjectURL(file),
          type: file.type.startsWith('image/') ? 'image' as const : 'video' as const,
        }))
      onChange([...files, ...newFiles])
    },
    [files, onChange],
  )

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current++
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current--
    if (dragCounter.current === 0) setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    dragCounter.current = 0
    setIsDragging(false)
    if (e.dataTransfer.files.length) {
      processFiles(e.dataTransfer.files)
    }
  }

  const removeFile = (id: string) => {
    const file = files.find((f) => f.id === id)
    if (file) URL.revokeObjectURL(file.previewUrl)
    onChange(files.filter((f) => f.id !== id))
  }

  return (
    <div className="space-y-3">
      <div
        onDragEnter={handleDragEnter}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={cn(
          "relative flex flex-col items-center justify-center gap-3 p-8 rounded-xl cursor-pointer transition-all duration-200",
          "border-2 border-dashed",
          isDragging
            ? "border-accent bg-accent/10 scale-[1.01]"
            : "border-border hover:border-accent/50 hover:bg-accent/5"
        )}
      >
        <div className={cn(
          "w-10 h-10 rounded-full flex items-center justify-center transition-colors",
          isDragging ? "bg-accent/20 text-accent-dark" : "bg-muted text-muted-foreground"
        )}>
          <Upload size={20} />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">
            {isDragging ? 'Drop files here' : 'Drag & drop media files'}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            or click to browse — images and videos accepted
          </p>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*,video/*"
          onChange={(e) => e.target.files && processFiles(e.target.files)}
          className="hidden"
        />
      </div>

      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
          >
            {files.map((media) => (
              <motion.div
                key={media.id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="relative group aspect-video rounded-lg overflow-hidden bg-muted"
              >
                {media.type === 'image' ? (
                  <img
                    src={media.previewUrl}
                    alt={media.file.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <video
                    src={media.previewUrl}
                    className="w-full h-full object-cover"
                    muted
                  />
                )}

                {/* Type badge */}
                <div className="absolute bottom-1.5 left-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 text-white text-[10px]">
                  {media.type === 'image' ? <ImageIcon size={10} /> : <Film size={10} />}
                  {media.type}
                </div>

                {/* Remove button */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeFile(media.id)
                  }}
                  className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 hover:bg-red-500 transition-all"
                >
                  <X size={12} />
                </button>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
