import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Smartphone, Loader2, ArrowLeft, Download,
} from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { cn, getTimeAgo } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { PromptSelector } from '@/components/shared/PromptSelector'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import type { UploadItem, ProductionItem } from '@/components/shared/VideoSourceSelector'
import type { SystemResource } from '@/types/project'

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

  // Prompt state
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')

  // Options
  const [blurredBg, setBlurredBg] = useState(false)
  const [sportsMode, setSportsMode] = useState(false)

  // Processing state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      api.system.listResources('prompt', 'orientation').catch(() => []),
    ]).then(([ups, prods, orientationPrompts]) => {
      setUploads(ups)
      setProductions(prods.filter((p: ProductionItem) => p.orientation === '16:9'))
      setPrompts(orientationPrompts)
      const active = orientationPrompts.find((p: SystemResource) => p.is_active)
      if (active) setPromptId(active.id)
    }).finally(() => setLoadingSources(false))
  }, [isViewMode])

  const handleSelectUpload = (upload: UploadItem) => {
    setVideoUrl(upload.video_signed_url)
    setGcsUri(upload.gcs_uri)
    setVideoFilename(upload.filename)
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
        prompt_id: promptId,
        blurred_bg: blurredBg,
        sports_mode: sportsMode,
      })
      navigate(`/orientations/${result.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSubmitting(false)
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

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <button onClick={() => navigate('/orientations')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Orientations
          </button>
          <span className="text-xs text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
        </div>

        <div className="space-y-2">
          <h2 className="text-lg font-heading font-bold text-foreground">{record.source_filename || 'Reframe'}</h2>
          <div className="flex items-center gap-2">
            <span className={cn("text-sm font-medium", statusCfg.color)}>{statusCfg.label}</span>
            {isProcessing && (
              <span className="text-xs text-muted-foreground">({record.progress_pct}%)</span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {record.blurred_bg && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-purple-500/10 text-purple-600 border border-purple-500/20">
                Blurred BG
              </span>
            )}
            {record.sports_mode && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-orange-500/10 text-orange-600 border border-orange-500/20">
                Sports Mode
              </span>
            )}
          </div>
        </div>

        {isProcessing && <ProgressBar progress={record.progress_pct} />}

        {record.status === 'failed' && record.error_message && (
          <ErrorDisplay error={record.error_message} size="md" />
        )}

        {record.status === 'completed' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
              {record.source_signed_url && (
                <div className="space-y-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Original (16:9)</h3>
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
                  <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Reframed (9:16)</h3>
                  <div className="aspect-[9/16] max-w-xs bg-black rounded-xl overflow-hidden border border-border">
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
                  <Download size={16} /> Download 9:16 Video
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

      {videoUrl && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Analysis Prompt</h3>
          <PromptSelector
            prompts={prompts}
            value={promptId}
            onChange={setPromptId}
            emptyMessage='No orientation prompts found. Using default. Create one in System Prompts with category "orientation".'
          />
        </div>
      )}

      {videoUrl && (
        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={blurredBg}
              onChange={(e) => setBlurredBg(e.target.checked)}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Blurred background fill
              </span>
              <p className="text-xs text-muted-foreground">
                Wider crop with blurred bars on top/bottom — shows more of the scene
              </p>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={sportsMode}
              onChange={(e) => setSportsMode(e.target.checked)}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Sports mode
              </span>
              <p className="text-xs text-muted-foreground">
                Faster panning to keep up with fast-moving action (basketball, football, etc.)
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
