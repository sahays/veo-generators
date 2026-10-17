import React, { useState } from 'react'
import {
  Play,
  FileVideo,
  CheckCircle2,
  Clock,
  ChevronRight,
  Film,
  Upload,
  Sparkles,
  Image,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { cn, formatFileSize } from '@/lib/utils'
import {
  ROUTE_MAP,
  useVideoSources,
  useImageSources,
  usePromptSources,
  type ConfirmationJobType,
  type UploadSourceItem,
  type ProductionSourceItem,
} from './useChatWidgetActions'

export const VideoResultCard: React.FC<{
  title: string
  status: string
  id: string
  type: ConfirmationJobType
}> = ({ title, status, id, type }) => (
  <div className="mt-2 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
    <div className="flex items-center gap-3 p-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-orange-100 text-orange-600 dark:bg-orange-900/40 dark:text-orange-400">
        <FileVideo size={20} />
      </div>
      <div className="flex-1 min-w-0">
        <h5 className="truncate text-xs font-semibold text-slate-900 dark:text-white">
          {title || 'Untitled Job'}
        </h5>
        <div className="flex items-center gap-1.5 mt-0.5">
          {status === 'completed' ? (
            <CheckCircle2 size={12} className="text-green-500" />
          ) : (
            <Clock size={12} className="text-amber-500 animate-pulse" />
          )}
          <span className="text-[10px] uppercase tracking-wider text-slate-500">{status}</span>
        </div>
      </div>
      <Link
        to={(ROUTE_MAP[type] || ROUTE_MAP.production)(id)}
        className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-600 transition-colors hover:bg-orange-600 hover:text-white dark:bg-slate-700 dark:text-slate-300"
      >
        <ChevronRight size={16} />
      </Link>
    </div>
    {status === 'completed' && (
      <div className="aspect-video bg-slate-900 flex items-center justify-center group relative cursor-pointer">
        <Play size={24} className="text-white opacity-50 group-hover:opacity-100 transition-opacity" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
      </div>
    )}
  </div>
)

const VideoSourceTabs: React.FC<{
  tab: 'uploads' | 'productions'
  onSelectTab: (tab: 'uploads' | 'productions') => void
}> = ({ tab, onSelectTab }) => (
  <div className="flex gap-1 bg-slate-100 p-1 rounded-lg dark:bg-slate-800">
    {(
      [
        ['uploads', Upload, 'Uploads'],
        ['productions', Film, 'Productions'],
      ] as const
    ).map(([key, Icon, label]) => (
      <Button
        key={key}
        variant="unstyled"
        onClick={() => onSelectTab(key)}
        className={cn(
          'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-[5px] text-[10px] font-bold uppercase tracking-wider transition-all',
          tab === key
            ? 'bg-white text-orange-600 shadow-sm dark:bg-slate-700 dark:text-orange-400'
            : 'text-slate-500',
        )}
      >
        <Icon size={12} /> {label}
      </Button>
    ))}
  </div>
)

const VideoSourceList: React.FC<{
  tab: 'uploads' | 'productions'
  uploads: UploadSourceItem[]
  productions: ProductionSourceItem[]
  onSelect: (gcs_uri: string, filename: string, type: string) => void
}> = ({ tab, uploads, productions, onSelect }) =>
  tab === 'uploads' ? (
    <>
      {uploads.map((u) => (
        <Button
          key={u.id}
          variant="unstyled"
          onClick={() => onSelect(u.gcs_uri, u.display_name || u.filename, 'upload')}
          className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-orange-500 hover:bg-orange-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-orange-900/20"
        >
          <FileVideo size={12} className="text-slate-400" />
          <div className="flex-1 min-w-0">
            <p className="truncate font-medium text-slate-900 dark:text-white">
              {u.display_name || u.filename}
            </p>
            <p className="text-[9px] text-slate-500">{formatFileSize(u.file_size_bytes)}</p>
          </div>
        </Button>
      ))}
    </>
  ) : (
    <>
      {productions.map((p) => (
        <Button
          key={p.id}
          variant="unstyled"
          onClick={() => onSelect(p.final_video_url, p.name, 'production')}
          className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-orange-500 hover:bg-orange-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-orange-900/20"
        >
          <Film size={12} className="text-slate-400" />
          <div className="flex-1 min-w-0">
            <p className="truncate font-medium text-slate-900 dark:text-white">{p.name}</p>
            <p className="text-[9px] text-slate-500">{p.orientation}</p>
          </div>
        </Button>
      ))}
    </>
  )

export const VideoSourcePicker: React.FC<{
  onSelect: (gcs_uri: string, filename: string, type: string) => void
}> = ({ onSelect }) => {
  const [tab, setTab] = useState<'uploads' | 'productions'>('uploads')
  const { uploads, productions, loading } = useVideoSources()

  return (
    <div className="mt-3 space-y-2">
      <VideoSourceTabs tab={tab} onSelectTab={setTab} />
      <div className="max-h-48 overflow-y-auto space-y-1 pr-1 scrollbar-thin">
        {loading ? (
          <div className="py-8 flex justify-center">
            <Clock className="animate-spin text-slate-300" size={16} />
          </div>
        ) : (
          <VideoSourceList
            tab={tab}
            uploads={uploads}
            productions={productions}
            onSelect={onSelect}
          />
        )}
      </div>
    </div>
  )
}

export const ImageSourcePicker: React.FC<{
  onSelect: (gcs_uri: string, filename: string) => void
}> = ({ onSelect }) => {
  const { images, loading } = useImageSources()

  return (
    <div className="mt-3 space-y-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1">
        <Image size={10} /> Select Image
      </p>
      <div className="max-h-48 overflow-y-auto space-y-1 pr-1 scrollbar-thin">
        {loading ? (
          <div className="py-8 flex justify-center">
            <Clock className="animate-spin text-slate-300" size={16} />
          </div>
        ) : images.length === 0 ? (
          <p className="px-1 text-[10px] italic text-slate-400">
            No uploaded images found. Upload one on the Adapts page first.
          </p>
        ) : (
          images.map((img) => (
            <Button
              key={img.id}
              variant="unstyled"
              onClick={() => onSelect(img.gcs_uri, img.display_name || img.filename)}
              className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-orange-500 hover:bg-orange-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-orange-900/20"
            >
              <img src={img.image_signed_url} alt="" className="h-8 w-8 flex-shrink-0 rounded object-cover" />
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-white">
                  {img.display_name || img.filename}
                </p>
                <p className="text-[9px] text-slate-500">{img.mime_type}</p>
              </div>
            </Button>
          ))
        )}
      </div>
    </div>
  )
}

export const PromptPicker: React.FC<{
  category: string
  onSelect: (id: string, name: string) => void
}> = ({ category, onSelect }) => {
  const { prompts, loading } = usePromptSources(category)

  return (
    <div className="mt-3 space-y-2">
      <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1">
        <Sparkles size={10} /> Select {category} Prompt
      </p>
      <div className="space-y-1">
        {loading ? (
          <div className="py-4 flex justify-center">
            <Clock className="animate-spin text-slate-300" size={16} />
          </div>
        ) : (
          prompts.map((p) => (
            <Button
              key={p.id}
              variant="unstyled"
              onClick={() => onSelect(p.id, p.name)}
              className={cn(
                'flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-left text-[11px] transition-all hover:border-orange-500 hover:bg-orange-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-orange-900/20',
                p.is_active &&
                  'border-amber-200 bg-amber-50/30 dark:border-amber-900/50 dark:bg-amber-900/10',
              )}
            >
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium text-slate-900 dark:text-white">{p.name}</p>
                <p className="text-[9px] text-slate-500 truncate">{p.description}</p>
              </div>
              {p.is_active && (
                <span className="text-[8px] font-bold bg-amber-100 text-amber-700 px-1 rounded dark:bg-amber-900/40 dark:text-amber-400">
                  ACTIVE
                </span>
              )}
            </Button>
          ))
        )}
      </div>
    </div>
  )
}
