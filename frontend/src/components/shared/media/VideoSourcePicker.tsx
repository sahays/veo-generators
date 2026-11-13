import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  VideoSourceSelector,
  type ProductionItem,
  type UploadItem,
} from '@/components/shared/VideoSourceSelector'
import { useVideoSourceState, type VideoSourceTab } from '@/hooks/useVideoSourceState'
import { cn } from '@/lib/utils'
import type { InsightSourceType } from '@/types/insights'

/**
 * Shared "pick a video" control: Uploads / Productions tabs, a name search and
 * a link to the Files page for adding a new video.
 *
 * Usage:
 *   const picker = useVideoSourcePicker({
 *     loadUploads: () => api.sceneAnalysis.listUploadSources(),
 *     loadProductions: () => api.sceneAnalysis.listProductionSources(),
 *   })
 *   <VideoSourcePicker picker={picker} />
 *   // picker.value is the PickedVideoSource to submit, or null.
 *   // picker.select(null) clears it.
 *
 * The value names the video by id only. The gs:// URI of the chosen row stays
 * inside the picker, where it highlights that row; it is never part of `value`.
 */

/** The picker's value: what a create request needs to name a video. */
export interface PickedVideoSource {
  source_type: InsightSourceType
  source_id: string
  /** Display name (upload display name / filename, or production name). */
  name: string
  /** Signed, playable URL for previewing the video. */
  video_url: string
}

export interface VideoSourcePickerLoaders {
  loadUploads: () => Promise<UploadItem[]>
  loadProductions: () => Promise<ProductionItem[]>
}

export interface VideoSourcePickerOptions {
  /** Tab shown first. Defaults to Uploads. */
  initialTab?: VideoSourceTab
  /** Set false to skip loading the lists (e.g. while the picker is hidden). */
  enabled?: boolean
}

/** State returned by `useVideoSourcePicker` and consumed by `VideoSourcePicker`. */
export interface VideoSourcePickerState {
  /** The selected video, or null. */
  value: PickedVideoSource | null
  /** Set the selection from outside, or clear it with `select(null)`. */
  select: (source: PickedVideoSource | null) => void
  /** True while the upload and production lists are loading. */
  loading: boolean
  sourceTab: VideoSourceTab
  setSourceTab: (tab: VideoSourceTab) => void
  /** Search text; filters both lists by name, case-insensitively. */
  query: string
  setQuery: (query: string) => void
  /** Uploads matching `query`. */
  uploads: UploadItem[]
  /** Productions matching `query`. */
  productions: ProductionItem[]
  /** Storage URI of the row picked in the list; used only to highlight it. */
  selectedUri: string | null
  pickUpload: (upload: UploadItem) => void
  pickProduction: (production: ProductionItem) => void
}

export interface VideoSourcePickerProps {
  /** State from `useVideoSourcePicker`. */
  picker: VideoSourcePickerState
  className?: string
}

interface Selection {
  source: PickedVideoSource
  uri: string | null
}

const UPLOADS_PATH = '/uploads'
const NO_UPLOADS_MESSAGE = 'No uploaded videos yet. Use "Upload new video" to add one in Files.'
const NO_PRODUCTIONS_MESSAGE = 'No completed productions found.'

const uploadName = (upload: UploadItem): string => upload.display_name || upload.filename

function filterByName<T>(items: T[], needle: string, nameOf: (item: T) => string): T[] {
  if (!needle) return items
  return items.filter((item) => nameOf(item).toLowerCase().includes(needle))
}

function emptyMessage(query: string, fallback: string): string {
  const trimmed = query.trim()
  return trimmed ? `No videos match "${trimmed}".` : fallback
}

const uploadSelection = (upload: UploadItem): Selection => ({
  source: { source_type: 'upload', source_id: upload.id, name: uploadName(upload), video_url: upload.video_signed_url },
  uri: upload.gcs_uri,
})

const productionSelection = (production: ProductionItem): Selection => ({
  source: { source_type: 'production', source_id: production.id, name: production.name, video_url: production.video_signed_url },
  uri: production.final_video_url,
})

/** Owns the lists, tab, search text and selection behind `VideoSourcePicker`. */
export function useVideoSourcePicker(
  loaders: VideoSourcePickerLoaders,
  options: VideoSourcePickerOptions = {},
): VideoSourcePickerState {
  const base = useVideoSourceState<UploadItem, ProductionItem>(loaders, options)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()
  const uploads = useMemo(
    () => filterByName(base.uploads, needle, (u) => `${u.display_name ?? ''} ${u.filename}`),
    [base.uploads, needle],
  )
  const productions = useMemo(() => filterByName(base.productions, needle, (p) => p.name), [base.productions, needle])

  return {
    value: selection?.source ?? null,
    select: (source) => setSelection(source ? { source, uri: null } : null),
    loading: base.loading,
    sourceTab: base.sourceTab,
    setSourceTab: base.setSourceTab,
    query,
    setQuery,
    uploads,
    productions,
    selectedUri: selection?.uri ?? null,
    pickUpload: (upload) => setSelection(uploadSelection(upload)),
    pickProduction: (production) => setSelection(productionSelection(production)),
  }
}

function PickerToolbar({
  query,
  onQueryChange,
}: {
  query: string
  onQueryChange: (query: string) => void
}): JSX.Element {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="relative flex-1">
        <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search videos by name"
          aria-label="Search videos by name"
          className="pl-9"
        />
      </div>
      <Button asChild variant="outline" size="sm" className="self-start sm:self-auto">
        <Link to={UPLOADS_PATH}>
          <Upload size={14} aria-hidden="true" />
          Upload new video
        </Link>
      </Button>
    </div>
  )
}

function SelectedSourceNotice({
  source,
  onClear,
}: {
  source: PickedVideoSource
  onClear: () => void
}): JSX.Element {
  return (
    <div role="status" className="flex items-center justify-between gap-3 rounded-[6px] border border-accent/30 bg-accent/5 px-3 py-2">
      <p className="min-w-0 truncate text-xs text-muted-foreground">
        Selected: <span className="font-medium text-foreground">{source.name}</span>
      </p>
      <Button variant="ghost" size="xs" icon={X} onClick={onClear} className="shrink-0">
        Clear selection
      </Button>
    </div>
  )
}

/** Tabs, search, upload link and selectable lists for choosing one video. */
export function VideoSourcePicker({ picker, className }: VideoSourcePickerProps): JSX.Element {
  return (
    <section aria-label="Video source" className={cn('space-y-3', className)}>
      <PickerToolbar query={picker.query} onQueryChange={picker.setQuery} />
      {picker.value && <SelectedSourceNotice source={picker.value} onClear={() => picker.select(null)} />}
      <VideoSourceSelector
        uploads={picker.uploads}
        productions={picker.productions}
        loading={picker.loading}
        sourceTab={picker.sourceTab}
        onTabChange={picker.setSourceTab}
        selectedUri={picker.selectedUri}
        onSelectUpload={picker.pickUpload}
        onSelectProduction={picker.pickProduction}
        emptyUploadsMessage={emptyMessage(picker.query, NO_UPLOADS_MESSAGE)}
        emptyProductionsMessage={emptyMessage(picker.query, NO_PRODUCTIONS_MESSAGE)}
      />
    </section>
  )
}
