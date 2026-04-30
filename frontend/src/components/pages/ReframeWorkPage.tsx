import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Smartphone, Loader2, ArrowLeft, RotateCcw } from 'lucide-react'
import { Button } from '@/components/Common'
import { Select } from '@/components/UI'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { cn } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { ReframeCompleted } from '@/components/pages/reframe/ReframeCompleted'
import { ReframePipelineLinks } from '@/components/pages/reframe/ReframePipelineLinks'

import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { WorkPageHeader } from '@/components/shared/WorkPageHeader'
import type { UploadItem, ProductionItem } from '@/components/shared/VideoSourceSelector'

const ACTIVE_STATUSES = ['pending', 'analyzing', 'processing', 'encoding']

const STATUS_CONFIG = buildStatusConfig(
  {
    pending: { label: 'Preparing to analyze...', color: 'text-amber-500' },
    analyzing: { label: 'Analyzing video with AI...', color: 'text-amber-500' },
    processing: { label: 'Reframing video...', color: 'text-blue-500' },
    encoding: { label: 'Encoding final output...', color: 'text-purple-500' },
  },
  {
    completed: { label: 'Reframe complete', color: 'text-emerald-500' },
    failed: { label: 'Reframe failed', color: 'text-red-500' },
  },
)

const CONTENT_TYPE_OPTIONS = [
  { value: 'movies', label: 'Movies', description: 'Films, drama, scripted — follows characters and story' },
  { value: 'documentaries', label: 'Documentaries', description: 'Interviews, narration, b-roll — tracks speaker and subject' },
  { value: 'sports', label: 'Sports', description: 'Live action, highlights — fast tracking on the play' },
  { value: 'podcasts', label: 'Podcasts', description: 'Podcasts, interviews, panels — centers the active speaker' },
  { value: 'promos', label: 'Promos', description: 'Ads, product showcases — keeps product and presenter visible' },
  { value: 'news', label: 'News', description: 'Anchors, field reports — follows the active reporter' },
  { value: 'other', label: 'Other', description: 'General reframing for other content' },
]

const CONTENT_TYPE_BADGE: Record<string, { label: string; className: string }> = {
  movies: { label: 'Movies', className: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
  documentaries: { label: 'Documentaries', className: 'bg-teal-500/10 text-teal-600 border-teal-500/20' },
  sports: { label: 'Sports', className: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  podcasts: { label: 'Podcasts', className: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  promos: { label: 'Promos', className: 'bg-pink-500/10 text-pink-600 border-pink-500/20' },
  news: { label: 'News', className: 'bg-red-500/10 text-red-600 border-red-500/20' },
  other: { label: 'Other', className: 'bg-gray-500/10 text-gray-600 border-gray-500/20' },
}

export const ReframeWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()
  const isViewMode = !!id

  const {
    sourceTab, setSourceTab,
    videoUrl, gcsUri, videoFilename,
    productions, uploads, loading: loadingSources,
    select,
  } = useVideoSourceState<UploadItem, ProductionItem>(
    {
      loadUploads: () => api.reframe.listUploadSources(),
      loadProductions: () =>
        api.reframe
          .listProductionSources()
          .then((prods) => prods.filter((p: ProductionItem) => p.orientation === '16:9')),
    },
    { enabled: !isViewMode },
  )

  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [contentType, setContentType] = useState('other')
  const [blurredBg, setBlurredBg] = useState(false)
  const [verticalSplit, setVerticalSplit] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { record, loading: recordLoading, error: pollError } = usePolling(
    id,
    api.reframe.get,
    ACTIVE_STATUSES,
  )

  const handleSelectUpload = (upload: UploadItem) =>
    select(upload.video_signed_url, upload.gcs_uri, upload.display_name || upload.filename)

  const handleSelectProduction = (prod: ProductionItem) =>
    select(prod.video_signed_url, prod.final_video_url, prod.name)

  const handleStartReframe = async () => {
    if (!gcsUri) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.reframe.create({
        gcs_uri: gcsUri,
        source_filename: videoFilename,
        content_type: contentType,
        blurred_bg: blurredBg,
        vertical_split: verticalSplit,
        model_id: modelConfig.modelId,
        region: modelConfig.region,
      })
      navigate(`/orientations/${result.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const [retrying, setRetrying] = useState(false)

  const handleRetry = async () => {
    if (!id) return
    setRetrying(true)
    try {
      await api.reframe.retry(id)
    } catch (err: any) {
      console.error('Failed to retry reframe', err)
    } finally {
      setRetrying(false)
    }
  }

  // --- View Mode ---
  if (isViewMode) {
    if (recordLoading) {
      return (
        <div className="flex flex-col items-center justify-center py-32 space-y-4">
          <Loader2 className="animate-spin text-accent" size={32} />
          <p className="text-sm text-muted-foreground">Loading reframe...</p>
        </div>
      )
    }

    if (pollError && !record) {
      return (
        <div className="space-y-4">
          <button onClick={() => navigate('/orientations')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Orientations
          </button>
          <ErrorDisplay error={pollError} size="md" />
        </div>
      )
    }

    if (!record) return null

    const isProcessing = ACTIVE_STATUSES.includes(record.status)
    const badge = CONTENT_TYPE_BADGE[record.content_type] || CONTENT_TYPE_BADGE.other
    const hasPrompt = !!(record.prompt_text_used || (record.prompt_variables && Object.keys(record.prompt_variables).length > 0))
    const hasTrackSummary = !!record.track_summary
    const speakerSegments = record.speaker_segments as Array<{ speaker_id: string; start_sec: number; end_sec: number }> | undefined
    const focalPoints = record.focal_points as Array<{ time_sec: number; x: number; y: number; confidence?: number; description?: string }> | undefined
    const geminiScenes = record.gemini_scenes as Array<any> | undefined

    return (
      <div className="space-y-6">
        <WorkPageHeader
          backPath="/orientations"
          backLabel="Back to Orientations"
          record={record}
          defaultName="Reframe"
          onSaveName={(name) => api.reframe.update(record.id, { display_name: name })}
          statusConfig={STATUS_CONFIG}
          activeStatuses={ACTIVE_STATUSES}
        >
          {record.content_type && record.content_type !== 'other' && (
            <span className={cn("px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border", badge.className)}>
              {badge.label}
            </span>
          )}
          {record.blurred_bg && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-purple-500/10 text-purple-600 border border-purple-500/20">
              Blurred BG
            </span>
          )}
          {record.vertical_split && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-cyan-500/10 text-cyan-600 border border-cyan-500/20">
              Vertical Split
            </span>
          )}
        </WorkPageHeader>

        {isProcessing && <ProgressBar progress={record.progress_pct} />}

        {record.status === 'failed' && (
          <div className="space-y-3">
            {record.error_message && <ErrorDisplay error={record.error_message} size="md" />}
            {isMaster && (
              <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetry} disabled={retrying}>
                {retrying ? 'Retrying...' : 'Retry'}
              </Button>
            )}
          </div>
        )}

        <ReframePipelineLinks
          recordId={record.id}
          vertical_split={record.vertical_split}
          hasTrackSummary={hasTrackSummary}
          hasPrompt={hasPrompt}
          hasGeminiScenes={!!(geminiScenes && geminiScenes.length > 0)}
          hasFocalPoints={!!(focalPoints && focalPoints.length > 0)}
          hasSpeakerSegments={!!(speakerSegments && speakerSegments.length > 0)}
        />

        {record.status === 'completed' && <ReframeCompleted record={record} />}
      </div>
    )
  }

  // --- Create Mode ---
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={() => navigate('/orientations')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Orientations
        </button>
      </div>

      <div className="space-y-1">
        <h2 className="text-lg font-heading font-bold text-foreground">New Reframe</h2>
        <p className="text-sm text-muted-foreground">Select a landscape (16:9) video to reframe to portrait (9:16)</p>
      </div>

      <VideoSourceSelector
        uploads={uploads}
        productions={productions}
        loading={loadingSources}
        sourceTab={sourceTab}
        onTabChange={setSourceTab}
        selectedUri={gcsUri}
        onSelectUpload={handleSelectUpload}
        onSelectProduction={handleSelectProduction}
        emptyProductionsMessage="No completed 16:9 productions found."
      />

      {videoUrl && (
        <div className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Selected Video</h3>
          <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border max-w-lg">
            <video
              src={videoUrl}
              controls
              className="w-full h-full object-contain"
            />
          </div>
          <p className="text-sm text-foreground font-medium">{videoFilename}</p>
        </div>
      )}

      {videoUrl && !verticalSplit && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Content Type</h3>
          <Select
            value={contentType}
            onChange={setContentType}
            options={CONTENT_TYPE_OPTIONS}
            placeholder="Select content type..."
          />
        </div>
      )}

      {/* Prompt selector hidden — content type now drives the prompt via strategy template */}

      {videoUrl && (
        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={blurredBg}
              onChange={(e) => { setBlurredBg(e.target.checked); if (e.target.checked) setVerticalSplit(false) }}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Blurred background fill
              </span>
              <p className="text-xs text-muted-foreground">
                4:5 output with blurred fill on the sides — wider than 9:16
              </p>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={verticalSplit}
              onChange={(e) => { setVerticalSplit(e.target.checked); if (e.target.checked) setBlurredBg(false) }}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Vertical split screen
              </span>
              <p className="text-xs text-muted-foreground">
                Split the landscape frame into left/right halves stacked vertically — no AI analysis needed
              </p>
            </div>
          </label>
        </div>
      )}

      <ErrorDisplay error={error} />

      <div className="flex items-center justify-end gap-4">
        <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} className="mt-2" />
        <Button
          icon={Smartphone}
          onClick={handleStartReframe}
          disabled={!gcsUri || submitting}
          className={cn(submitting && "[&_svg]:animate-spin")}
        >
          {submitting ? 'Starting...' : 'Start Reframe'}
        </Button>
      </div>
    </div>
  )
}
