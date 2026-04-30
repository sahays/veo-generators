import { motion } from 'framer-motion'
import {
  Archive,
  CheckCircle2,
  File as FileIcon,
  Loader2,
  Shrink,
} from 'lucide-react'
import { cn, formatFileSize, getTimeAgo } from '@/lib/utils'
import {
  FILE_TYPE_ICONS,
  FILE_TYPE_STYLES,
} from '@/components/pages/uploads/fileTypeStyles'
import type { UploadRecord } from '@/types/project'

interface Props {
  record: UploadRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  onCompress?: (resolution: string, e: React.MouseEvent) => void
  compressingResolution?: string | null
  canEdit: boolean
}

export const UploadCard = ({
  record,
  onClick,
  onArchive,
  onCompress,
  compressingResolution,
  canEdit,
}: Props) => {
  const TypeIcon = FILE_TYPE_ICONS[record.file_type] || FileIcon
  const isChild = !!record.parent_upload_id
  const resolutionBadge =
    record.resolution_label || (record.file_type === 'video' && !isChild ? 'original' : null)

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-4 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
    >
      <div className="flex items-center gap-1.5 mb-2">
        <span
          className={cn(
            'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0',
            FILE_TYPE_STYLES[record.file_type] || FILE_TYPE_STYLES.other,
          )}
        >
          <span className="flex items-center gap-1">
            <TypeIcon size={8} />
            {record.file_type}
          </span>
        </span>
        {resolutionBadge && (
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border shrink-0',
              isChild
                ? 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20'
                : 'bg-gray-500/10 text-gray-500 border-gray-500/20',
            )}
          >
            {resolutionBadge}
          </span>
        )}
      </div>

      <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 mb-1">
        {record.display_name || record.filename}
      </h4>

      <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-3">
        <span>{formatFileSize(record.file_size_bytes)}</span>
        <span className="text-muted-foreground/50">&middot;</span>
        <span>{getTimeAgo(record.createdAt)}</span>
      </div>

      {canEdit && record.file_type === 'video' && !isChild && (
        <div className="flex items-center gap-2 mb-2">
          {(['480p', '720p'] as const).map((res) => {
            const existing = record.compressed_variants.find((v) => v.resolution === res)
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
                  'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all',
                  isSucceeded
                    ? 'bg-emerald-500/10 text-emerald-600 cursor-default'
                    : isProcessing || isCompressingThis
                      ? 'bg-amber-500/10 text-amber-600 cursor-wait'
                      : 'bg-muted hover:bg-accent/10 hover:text-accent-dark text-foreground cursor-pointer',
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

      {canEdit && (
        <div className="flex items-center justify-end">
          <button
            onClick={onArchive}
            className="p-1 -m-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
            title="Archive"
          >
            <Archive size={12} />
          </button>
        </div>
      )}
    </motion.button>
  )
}
