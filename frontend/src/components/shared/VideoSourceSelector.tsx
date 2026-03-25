import {
  Loader2, Film, FileVideo, ChevronRight, Upload,
} from 'lucide-react'
import { cn, getTimeAgo, formatFileSize } from '@/lib/utils'

type VideoSourceTab = 'productions' | 'past-uploads'

export interface UploadItem {
  id: string
  filename: string
  gcs_uri: string
  video_signed_url: string
  file_size_bytes: number
  createdAt: string
}

export interface ProductionItem {
  id: string
  name: string
  orientation: string
  final_video_url: string
  video_signed_url: string
  createdAt: string
}

interface VideoSourceSelectorProps {
  uploads: UploadItem[]
  productions: ProductionItem[]
  loading: boolean
  sourceTab: VideoSourceTab
  onTabChange: (tab: VideoSourceTab) => void
  selectedUri: string | null
  onSelectUpload: (upload: UploadItem) => void
  onSelectProduction: (production: ProductionItem) => void
  emptyUploadsMessage?: string
  emptyProductionsMessage?: string
}

export function VideoSourceSelector({
  uploads,
  productions,
  loading,
  sourceTab,
  onTabChange,
  selectedUri,
  onSelectUpload,
  onSelectProduction,
  emptyUploadsMessage = 'No uploaded videos found. Upload a video in the Files section first.',
  emptyProductionsMessage = 'No completed productions found.',
}: VideoSourceSelectorProps): JSX.Element {
  const tabs = [
    { key: 'past-uploads' as VideoSourceTab, label: 'Uploads', icon: Upload },
    { key: 'productions' as VideoSourceTab, label: 'Productions', icon: Film },
  ]

  return (
    <>
      {/* Tab bar */}
      <div className="flex gap-1 bg-muted/50 rounded-lg p-1">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => onTabChange(tab.key)}
            className={cn(
              "flex items-center gap-1.5 flex-1 justify-center px-3 py-2 rounded-md text-xs font-medium transition-all cursor-pointer",
              sourceTab === tab.key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Source list */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="animate-spin text-accent" size={24} />
        </div>
      ) : (
        <div className="space-y-2">
          {sourceTab === 'past-uploads' ? (
            uploads.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">{emptyUploadsMessage}</p>
            ) : (
              uploads.map((u) => (
                <button
                  key={u.id}
                  onClick={() => onSelectUpload(u)}
                  className={cn(
                    "w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left cursor-pointer",
                    selectedUri === u.gcs_uri
                      ? "border-accent bg-accent/5"
                      : "border-border hover:border-accent/40 bg-card"
                  )}
                >
                  <FileVideo size={18} className="text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{u.filename}</p>
                    <p className="text-[10px] text-muted-foreground">{formatFileSize(u.file_size_bytes)} &middot; {getTimeAgo(u.createdAt)}</p>
                  </div>
                  <ChevronRight size={16} className="text-muted-foreground shrink-0" />
                </button>
              ))
            )
          ) : (
            productions.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">{emptyProductionsMessage}</p>
            ) : (
              productions.map((p) => (
                <button
                  key={p.id}
                  onClick={() => onSelectProduction(p)}
                  className={cn(
                    "w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left cursor-pointer",
                    selectedUri === p.final_video_url
                      ? "border-accent bg-accent/5"
                      : "border-border hover:border-accent/40 bg-card"
                  )}
                >
                  <Film size={18} className="text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{p.name}</p>
                    <p className="text-[10px] text-muted-foreground">{p.orientation} &middot; {getTimeAgo(p.createdAt)}</p>
                  </div>
                  <ChevronRight size={16} className="text-muted-foreground shrink-0" />
                </button>
              ))
            )
          )}
        </div>
      )}
    </>
  )
}
