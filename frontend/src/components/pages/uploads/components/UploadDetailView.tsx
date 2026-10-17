import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  Download,
  ExternalLink,
  File as FileIcon,
  Loader2,
  Pencil,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/hooks/useApiClient'
import { useAuthStore } from '@/store/useAuthStore'
import { cn, formatFileSize, getTimeAgo } from '@/lib/utils'
import {
  FILE_TYPE_ICONS,
  FILE_TYPE_STYLES,
} from '@/components/pages/uploads/components/fileTypeStyles'
import type { CompressedVariant, UploadRecord } from '@/types/project'

const UploadDetailTitleRow = ({
  record,
  canWrite,
  onSaveName,
}: {
  record: UploadRecord
  canWrite: boolean
  onSaveName: (name: string) => Promise<void>
}) => {
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')
  const TypeIcon = FILE_TYPE_ICONS[record.file_type] || FileIcon
  const isChild = !!record.parent_upload_id

  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          'px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border',
          FILE_TYPE_STYLES[record.file_type] || FILE_TYPE_STYLES.other,
        )}
      >
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
      {isEditingName ? (
        <form
          className="flex items-center gap-2 flex-1"
          onSubmit={async (e) => {
            e.preventDefault()
            await onSaveName(editName)
            setIsEditingName(false)
          }}
        >
          <Input
            autoFocus
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            className="h-8 text-base font-heading font-bold text-foreground bg-muted px-2 py-0.5"
          />
          <Button type="submit" variant="ghost" size="icon" className="h-7 w-7 text-accent hover:text-accent-dark">
            <Check size={16} />
          </Button>
        </form>
      ) : canWrite ? (
        <Button
          variant="unstyled"
          className="flex items-center gap-2 text-base font-heading font-bold text-foreground hover:text-accent-dark transition-colors"
          onClick={() => {
            setEditName(record.display_name || record.filename)
            setIsEditingName(true)
          }}
        >
          {record.display_name || record.filename}
          <Pencil size={12} className="text-muted-foreground" />
        </Button>
      ) : (
        <span className="text-base font-heading font-bold text-foreground">
          {record.display_name || record.filename}
        </span>
      )}
    </div>
  )
}

const UploadDetailMetadataCard = ({
  record,
  canWrite,
  onSaveName,
  onNavigateUpload,
}: {
  record: UploadRecord
  canWrite: boolean
  onSaveName: (name: string) => Promise<void>
  onNavigateUpload: (id: string) => void
}) => {
  const isChild = !!record.parent_upload_id
  return (
    <div className="glass bg-card rounded-xl p-5 space-y-3">
      <UploadDetailTitleRow record={record} canWrite={canWrite} onSaveName={onSaveName} />
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
        {isChild && record.parent_upload_id && (
          <div>
            <span className="text-muted-foreground">Source</span>
            <Button
              variant="link"
              size="xs"
              onClick={() => onNavigateUpload(record.parent_upload_id!)}
              className="flex items-center gap-1 px-0 h-auto font-medium text-accent hover:text-accent-dark"
            >
              View original
              <ExternalLink size={10} />
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

const CompressedVariantsCard = ({
  variants,
  onNavigateUpload,
}: {
  variants: CompressedVariant[]
  onNavigateUpload: (id: string) => void
}) => (
  <div className="glass bg-card rounded-xl p-5 space-y-3">
    <h4 className="text-sm font-heading font-bold text-foreground">Compressed Variants</h4>
    <div className="space-y-2">
      {variants.map((v, i) => (
        <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-muted/50">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium',
                v.status === 'succeeded'
                  ? 'text-emerald-600 bg-emerald-500/10'
                  : v.status === 'processing'
                    ? 'text-amber-600 bg-amber-500/10'
                    : v.status === 'failed'
                      ? 'text-red-600 bg-red-500/10'
                      : 'text-gray-500 bg-gray-500/10',
              )}
            >
              {v.status === 'processing' && <Loader2 size={9} className="animate-spin" />}
              {v.status === 'succeeded' && <CheckCircle2 size={9} />}
              {v.status === 'failed' && <XCircle size={9} />}
              {v.status}
            </span>
            <span className="text-xs font-medium text-foreground">{v.resolution}</span>
          </div>
          <div className="flex items-center gap-3">
            {v.child_upload_id && (
              <Button
                variant="link"
                size="xs"
                onClick={() => onNavigateUpload(v.child_upload_id!)}
                className="flex items-center gap-1 px-0 h-auto text-xs text-accent hover:text-accent-dark"
              >
                <ExternalLink size={12} />
                View record
              </Button>
            )}
            {v.status === 'succeeded' && v.signed_url && (
              <Button
                variant="link"
                size="xs"
                href={v.signed_url}
                download
                icon={Download}
                iconSize={12}
                className="text-xs text-accent hover:text-accent-dark px-0 h-auto"
                onClick={(e) => e.stopPropagation()}
              >
                Download
              </Button>
            )}
          </div>
        </div>
      ))}
    </div>
  </div>
)

const UploadMediaPreview = ({ record }: { record: UploadRecord }) => {
  if (!record.signed_url) return null
  return (
    <div className="glass bg-card rounded-xl overflow-hidden border border-border">
      {record.file_type === 'video' ? (
        <video src={record.signed_url} controls className="w-full max-h-[400px] bg-black" />
      ) : record.file_type === 'image' ? (
        <img
          src={record.signed_url}
          alt={record.display_name || record.filename}
          className="w-full max-h-[400px] object-contain bg-black"
        />
      ) : null}
    </div>
  )
}

const UploadDetailBody = ({
  record,
  canWrite,
  onBack,
  onSaveName,
  onNavigateUpload,
}: {
  record: UploadRecord
  canWrite: boolean
  onBack: () => void
  onSaveName: (editName: string) => Promise<void>
  onNavigateUpload: (uid: string) => void
}) => (
  <div className="space-y-6">
    <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={onBack} className="text-muted-foreground hover:text-foreground -ml-2">
      Back to files
    </Button>
    <UploadMediaPreview record={record} />
    <UploadDetailMetadataCard record={record} canWrite={canWrite} onSaveName={onSaveName} onNavigateUpload={onNavigateUpload} />
    {record.compressed_variants.length > 0 && <CompressedVariantsCard variants={record.compressed_variants} onNavigateUpload={onNavigateUpload} />}
  </div>
)

export const UploadDetailView = ({ id }: { id: string }) => {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [record, setRecord] = useState<UploadRecord | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const fetchRecord = useCallback(async () => {
    try { setRecord(await api.uploads.get(id)) } catch { /* ignore */ }
  }, [id])

  useEffect(() => { fetchRecord().finally(() => setIsLoading(false)) }, [fetchRecord])

  if (isLoading) {
    return <div className="flex flex-col items-center justify-center py-32 space-y-4"><Loader2 className="animate-spin text-accent" size={32} /><p className="text-sm text-muted-foreground">Loading file...</p></div>
  }
  if (!record) {
    return <div className="text-center py-16"><p className="text-sm text-muted-foreground">File not found</p><Button variant="link" size="sm" onClick={() => navigate('/uploads')} className="mt-2">Back to files</Button></div>
  }
  return (
    <UploadDetailBody
      record={record}
      canWrite={canWrite}
      onBack={() => navigate('/uploads')}
      onSaveName={async (editName) => { await api.uploads.update(record.id, { display_name: editName }); setRecord({ ...record, display_name: editName }) }}
      onNavigateUpload={(uid) => navigate(`/uploads/${uid}`)}
    />
  )
}

