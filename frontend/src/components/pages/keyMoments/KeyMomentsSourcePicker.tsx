import { ChevronRight, FileVideo, Film, Loader2 } from 'lucide-react'
import { Card } from '@/components/Common'
import { cn, formatFileSize, getTimeAgo } from '@/lib/utils'
import type { VideoSourceTab } from '@/hooks/useVideoSourceState'
import type { CompletedProductionSource, UploadRecord } from '@/types/project'

interface Props {
  sourceTab: VideoSourceTab
  setSourceTab: (tab: VideoSourceTab) => void
  productions: CompletedProductionSource[]
  uploads: UploadRecord[]
  loading: boolean
  onSelectProduction: (prod: CompletedProductionSource) => void
  onSelectUpload: (record: UploadRecord) => void
  onNavigateUploads: () => void
}

const TABS: { key: VideoSourceTab; label: string; icon: typeof Film }[] = [
  { key: 'productions', label: 'Productions', icon: Film },
  { key: 'past-uploads', label: 'Files', icon: FileVideo },
]

export const KeyMomentsSourcePicker = ({
  sourceTab,
  setSourceTab,
  productions,
  uploads,
  loading,
  onSelectProduction,
  onSelectUpload,
  onNavigateUploads,
}: Props) => (
  <Card className="overflow-visible">
    <div className="px-5 pt-5 pb-3">
      <div className="flex gap-1 bg-muted/50 rounded-lg p-1">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setSourceTab(tab.key)}
            className={cn(
              'flex items-center gap-1.5 flex-1 justify-center px-3 py-2 rounded-md text-xs font-medium transition-all cursor-pointer',
              sourceTab === tab.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>
    </div>

    <div className="px-5 pb-5">
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="animate-spin text-accent" size={24} />
        </div>
      ) : sourceTab === 'productions' ? (
        productions.length === 0 ? (
          <p className="text-xs text-muted-foreground py-8 text-center">
            No completed productions with video found.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {productions.map((prod) => (
              <button
                key={prod.id}
                onClick={() => onSelectProduction(prod)}
                className="flex items-center gap-3 p-3 rounded-lg border border-border bg-card hover:border-accent/50 hover:bg-accent/5 transition-all text-left cursor-pointer group"
              >
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center shrink-0">
                  <Film size={16} className="text-indigo-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-foreground truncate group-hover:text-accent-dark transition-colors">
                    {prod.name}
                  </p>
                  <p className="text-[10px] text-muted-foreground">{prod.type}</p>
                </div>
                <ChevronRight size={14} className="text-muted-foreground shrink-0" />
              </button>
            ))}
          </div>
        )
      ) : uploads.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-xs text-muted-foreground mb-2">No video files found.</p>
          <button
            onClick={onNavigateUploads}
            className="text-xs text-accent hover:text-accent-dark transition-colors"
          >
            Go to Files to add videos
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {uploads.map((record) => (
            <button
              key={record.id}
              onClick={() => onSelectUpload(record)}
              className="flex items-center gap-3 w-full p-3 rounded-lg border border-border bg-card hover:border-accent/50 hover:bg-accent/5 transition-all text-left cursor-pointer group"
            >
              <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
                <FileVideo size={16} className="text-accent-dark" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-foreground truncate group-hover:text-accent-dark transition-colors">
                  {record.display_name || record.filename}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {formatFileSize(record.file_size_bytes)}
                  {record.resolution_label && ` · ${record.resolution_label}`}
                  {' · '}{getTimeAgo(record.createdAt)}
                </p>
              </div>
              <ChevronRight size={14} className="text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  </Card>
)
