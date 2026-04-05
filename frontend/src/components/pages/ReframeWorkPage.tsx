import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  Smartphone, Loader2, ArrowLeft, Download, RotateCcw, Pencil, Check,
  ExternalLink,
} from 'lucide-react'
import { Button, AnchorHeading } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import { cn, getTimeAgo } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'

import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import type { UploadItem, ProductionItem } from '@/components/shared/VideoSourceSelector'


type VideoSourceTab = 'productions' | 'past-uploads'

const ACTIVE_STATUSES = ['pending', 'analyzing', 'processing', 'encoding']

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: 'Preparing to analyze...', color: 'text-amber-500' },
  analyzing: { label: 'Analyzing video with AI...', color: 'text-amber-500' },
  processing: { label: 'Reframing video...', color: 'text-blue-500' },
  encoding: { label: 'Encoding final output...', color: 'text-purple-500' },
  completed: { label: 'Reframe complete', color: 'text-emerald-500' },
  failed: { label: 'Reframe failed', color: 'text-red-500' },
}

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
  const isViewMode = !!id

  // Video source state
  const [sourceTab, setSourceTab] = useState<VideoSourceTab>('past-uploads')
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [gcsUri, setGcsUri] = useState<string | null>(null)
  const [videoFilename, setVideoFilename] = useState('')

  // Source data
  const [productions, setProductions] = useState<ProductionItem[]>([])
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [loadingSources, setLoadingSources] = useState(false)

  // Options
  const [contentType, setContentType] = useState('other')
  const [blurredBg, setBlurredBg] = useState(false)
  const [verticalSplit, setVerticalSplit] = useState(false)

  // Processing state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Name editing
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  // View mode polling
  const { record, loading: recordLoading, error: pollError } = usePolling(
    id,
    api.reframe.get,
    ACTIVE_STATUSES,
  )

  // Load sources and prompts for create mode
  useEffect(() => {
    if (isViewMode) return
    setLoadingSources(true)
    Promise.all([
      api.reframe.listUploadSources().catch(() => []),
      api.reframe.listProductionSources().catch(() => []),
    ]).then(([ups, prods]) => {
      setUploads(ups)
      setProductions(prods.filter((p: ProductionItem) => p.orientation === '16:9'))
    }).finally(() => setLoadingSources(false))
  }, [isViewMode])

  const handleSelectUpload = (upload: UploadItem) => {
    setVideoUrl(upload.video_signed_url)
    setGcsUri(upload.gcs_uri)
    setVideoFilename(upload.display_name || upload.filename)
  }

  const handleSelectProduction = (prod: ProductionItem) => {
    setVideoUrl(prod.video_signed_url)
    setGcsUri(prod.final_video_url)
    setVideoFilename(prod.name)
  }

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

    const statusCfg = STATUS_CONFIG[record.status] || STATUS_CONFIG.pending
    const isProcessing = ACTIVE_STATUSES.includes(record.status)
    const badge = CONTENT_TYPE_BADGE[record.content_type] || CONTENT_TYPE_BADGE.other
    const hasPrompt = !!(record.prompt_text_used || (record.prompt_variables && Object.keys(record.prompt_variables).length > 0))
    const hasTrackSummary = !!record.track_summary
    const speakerSegments = record.speaker_segments as Array<{ speaker_id: string; start_sec: number; end_sec: number }> | undefined
    const focalPoints = record.focal_points as Array<{ time_sec: number; x: number; y: number; confidence?: number; description?: string }> | undefined
    const geminiScenes = record.gemini_scenes as Array<any> | undefined

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <button onClick={() => navigate('/orientations')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Orientations
          </button>
          <span className="text-xs text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
        </div>

        <div className="space-y-2">
          {isEditingName ? (
            <form className="flex items-center gap-2" onSubmit={async (e) => {
              e.preventDefault()
              await api.reframe.update(record.id, { display_name: editName })
              record.display_name = editName
              setIsEditingName(false)
            }}>
              <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                className="text-lg font-heading font-bold text-foreground bg-muted px-2 py-0.5 rounded border border-border focus:outline-none focus:ring-1 focus:ring-accent" />
              <button type="submit" className="text-accent hover:text-accent-dark"><Check size={16} /></button>
            </form>
          ) : (
            <button className="flex items-center gap-2 text-lg font-heading font-bold text-foreground hover:text-accent-dark transition-colors"
              onClick={() => { setEditName(record.display_name || record.source_filename || 'Reframe'); setIsEditingName(true) }}>
              {record.display_name || record.source_filename || 'Reframe'}
              <Pencil size={12} className="text-muted-foreground" />
            </button>
          )}
          <div className="flex items-center gap-2">
            <span className={cn("text-sm font-medium", statusCfg.color)}>{statusCfg.label}</span>
            {isProcessing && (
              <span className="text-xs text-muted-foreground">({record.progress_pct}%)</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
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
          </div>
        </div>

        {isProcessing && <ProgressBar progress={record.progress_pct} />}

        {record.status === 'failed' && (
          <div className="space-y-3">
            {record.error_message && <ErrorDisplay error={record.error_message} size="md" />}
            <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetry} disabled={retrying}>
              {retrying ? 'Retrying...' : 'Retry'}
            </Button>
          </div>
        )}

        {/* AI Pipeline Output Links — in pipeline order */}
        {!record.vertical_split && (hasTrackSummary || hasPrompt || geminiScenes?.length || focalPoints?.length || speakerSegments?.length) && (
          <div className="flex flex-wrap gap-2">
            {hasTrackSummary && (
              <Link
                to={`/orientations/${record.id}/mediapipe`}
                target="_blank"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                MediaPipe <ExternalLink size={12} />
              </Link>
            )}
            {speakerSegments && speakerSegments.length > 0 && (
              <Link
                to={`/orientations/${record.id}/chirp`}
                target="_blank"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                Chirp <ExternalLink size={12} />
              </Link>
            )}
            {hasPrompt && (
              <Link
                to={`/orientations/${record.id}/prompt`}
                target="_blank"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                Prompt <ExternalLink size={12} />
              </Link>
            )}
            {geminiScenes && geminiScenes.length > 0 && (
              <Link
                to={`/orientations/${record.id}/gemini`}
                target="_blank"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                Gemini <ExternalLink size={12} />
              </Link>
            )}
            {focalPoints && focalPoints.length > 0 && (
              <Link
                to={`/orientations/${record.id}/focal-points`}
                target="_blank"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              >
                Focal Points <ExternalLink size={12} />
              </Link>
            )}
          </div>
        )}

        {record.status === 'completed' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
              {record.source_signed_url && (
                <div className="space-y-2">
                  <AnchorHeading id="original-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Original (16:9)</AnchorHeading>
                  <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border">
                    <video
                      src={record.source_signed_url}
                      controls
                      className="w-full h-full object-contain"
                    />
                  </div>
                </div>
              )}

              {record.output_signed_url && (
                <div className="space-y-2">
                  <AnchorHeading id="reframed-video" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Reframed ({record.blurred_bg ? '4:5' : '9:16'})
                  </AnchorHeading>
                  <div className={cn(
                    "bg-black rounded-xl overflow-hidden border border-border",
                    record.blurred_bg ? "aspect-[4/5] max-w-sm" : "aspect-[9/16] max-w-xs"
                  )}>
                    <video
                      src={record.output_signed_url}
                      controls
                      className="w-full h-full object-contain"
                    />
                  </div>
                </div>
              )}
            </div>

            {record.output_signed_url && (
              <div className="flex gap-3">
                <a
                  href={record.output_signed_url}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-dark transition-colors"
                >
                  <Download size={16} /> Download {record.blurred_bg ? '4:5' : '9:16'} Video
                </a>
              </div>
            )}

            {record.usage && record.usage.cost_usd > 0 && (
              <div className="text-xs text-muted-foreground">
                AI cost: ${record.usage.cost_usd.toFixed(4)} ({record.usage.input_tokens + record.usage.output_tokens} tokens)
              </div>
            )}
          </div>
        )}
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

      <div className="flex justify-end">
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
