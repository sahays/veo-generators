import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Scissors, Loader2, ArrowLeft, Download, RotateCcw, Pencil, Check,
} from 'lucide-react'
import { Button, AnchorHeading } from '@/components/Common'
import { api } from '@/lib/api'
import { cn, getTimeAgo } from '@/lib/utils'
import { useAuthStore } from '@/store/useAuthStore'
import { usePolling } from '@/hooks/usePolling'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { PromptSelector } from '@/components/shared/PromptSelector'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import type { UploadItem, ProductionItem } from '@/components/shared/VideoSourceSelector'
import type { SystemResource } from '@/types/project'

type VideoSourceTab = 'productions' | 'past-uploads'

interface PromoSegment {
  title: string
  timestamp_start: string
  timestamp_end: string
  description: string
  overlay_signed_url?: string
}

const ACTIVE_STATUSES = ['pending', 'analyzing', 'extracting', 'stitching', 'encoding']

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: 'Preparing to analyze...', color: 'text-amber-500' },
  analyzing: { label: 'Analyzing video with AI...', color: 'text-amber-500' },
  extracting: { label: 'Extracting best moments...', color: 'text-blue-500' },
  stitching: { label: 'Stitching promo together...', color: 'text-indigo-500' },
  encoding: { label: 'Encoding final output...', color: 'text-purple-500' },
  completed: { label: 'Promo complete', color: 'text-emerald-500' },
  failed: { label: 'Promo generation failed', color: 'text-red-500' },
}

export const PromoWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  useAuthStore()
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

  // Duration state
  const [targetDuration, setTargetDuration] = useState(60)

  // Prompt state
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')

  // Options
  const [textOverlay, setTextOverlay] = useState(false)
  const [generateThumbnail, setGenerateThumbnail] = useState(false)

  // Name editing
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  // Processing state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // View mode polling
  const { record, loading: recordLoading, error: pollError } = usePolling(
    id,
    api.promo.get,
    ACTIVE_STATUSES,
  )

  // Load sources and prompts for create mode
  useEffect(() => {
    if (isViewMode) return
    setLoadingSources(true)
    Promise.all([
      api.promo.listUploadSources().catch(() => []),
      api.promo.listProductionSources().catch(() => []),
      api.system.listResources('prompt', 'promo').catch(() => []),
    ]).then(([ups, prods, promoPrompts]) => {
      setUploads(ups)
      setProductions(prods)
      setPrompts(promoPrompts)
      const active = promoPrompts.find((p: SystemResource) => p.is_active)
      if (active) setPromptId(active.id)
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

  const handleGeneratePromo = async () => {
    if (!gcsUri) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.promo.create({
        gcs_uri: gcsUri,
        source_filename: videoFilename,
        prompt_id: promptId || undefined,
        target_duration: targetDuration,
        text_overlay: textOverlay,
        generate_thumbnail: generateThumbnail,
      })
      navigate(`/promos/${result.id}`, { replace: true })
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
      await api.promo.retry(id)
    } catch (err: any) {
      console.error('Failed to retry promo', err)
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
          <p className="text-sm text-muted-foreground">Loading promo...</p>
        </div>
      )
    }

    if (pollError && !record) {
      return (
        <div className="space-y-4">
          <button onClick={() => navigate('/promos')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Promos
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
          <button onClick={() => navigate('/promos')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Promos
          </button>
          <span className="text-xs text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
        </div>

        <div className="space-y-2">
          {isEditingName ? (
            <form className="flex items-center gap-2" onSubmit={async (e) => {
              e.preventDefault()
              await api.promo.update(record.id, { display_name: editName })
              record.display_name = editName
              setIsEditingName(false)
            }}>
              <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                className="text-lg font-heading font-bold text-foreground bg-muted px-2 py-0.5 rounded border border-border focus:outline-none focus:ring-1 focus:ring-accent" />
              <button type="submit" className="text-accent hover:text-accent-dark"><Check size={16} /></button>
            </form>
          ) : (
            <button className="flex items-center gap-2 text-lg font-heading font-bold text-foreground hover:text-accent-dark transition-colors"
              onClick={() => { setEditName(record.display_name || record.source_filename || 'Promo'); setIsEditingName(true) }}>
              {record.display_name || record.source_filename || 'Promo'}
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
            {record.target_duration && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-slate-500/10 text-slate-600 border border-slate-500/20">
                {record.target_duration}s target
              </span>
            )}
            {record.generate_thumbnail && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-indigo-500/10 text-indigo-600 border border-indigo-500/20">
                Thumbnail
              </span>
            )}
            {record.text_overlay && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-purple-500/10 text-purple-600 border border-purple-500/20">
                Text Overlays
              </span>
            )}
            {record.prompt_name && (
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-600 border border-amber-500/20">
                {record.prompt_name}
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

        {record.status === 'completed' && (
          <div className="space-y-6">
            {record.output_signed_url && (
              <div className="space-y-2">
                <AnchorHeading id="promo-output" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Promo Output</AnchorHeading>
                <div className="aspect-video bg-black rounded-xl overflow-hidden border border-border max-w-2xl">
                  <video
                    src={record.output_signed_url}
                    controls
                    className="w-full h-full object-contain"
                  />
                </div>
              </div>
            )}

            {record.output_signed_url && (
              <div className="flex gap-3">
                <a
                  href={record.output_signed_url}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-dark transition-colors"
                >
                  <Download size={16} /> Download Promo
                </a>
              </div>
            )}

            {record.thumbnail_signed_url && (
              <div className="space-y-2">
                <AnchorHeading id="title-card" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Title Card</AnchorHeading>
                <img
                  src={record.thumbnail_signed_url}
                  alt="Title card collage"
                  className="rounded-xl border border-border max-w-md"
                />
              </div>
            )}

            {record.segments && record.segments.length > 0 && (
              <div className="space-y-3">
                <AnchorHeading id="selected-moments" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Selected Moments</AnchorHeading>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {record.segments.map((seg: PromoSegment, i: number) => (
                    <div
                      key={i}
                      className="glass bg-card p-4 rounded-xl border border-border"
                    >
                      {seg.overlay_signed_url && (
                        <img
                          src={seg.overlay_signed_url}
                          alt={seg.title}
                          className="w-full rounded-lg mb-2 bg-black"
                        />
                      )}
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-mono text-muted-foreground">
                          {seg.timestamp_start} - {seg.timestamp_end}
                        </span>
                      </div>
                      <h4 className="text-sm font-heading font-bold text-foreground mb-1">{seg.title}</h4>
                      <p className="text-xs text-muted-foreground line-clamp-2">{seg.description}</p>
                    </div>
                  ))}
                </div>
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
        <button onClick={() => navigate('/promos')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Promos
        </button>
      </div>

      <div className="space-y-1">
        <h2 className="text-lg font-heading font-bold text-foreground">New Promo</h2>
        <p className="text-sm text-muted-foreground">Select a video to generate a promotional highlight reel</p>
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
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Promo Prompt</h3>
          <PromptSelector
            prompts={prompts}
            value={promptId}
            onChange={setPromptId}
            emptyMessage='No promo prompts found. Using default. Create one in System Prompts with category "promo".'
          />
        </div>
      )}

      {videoUrl && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Target Duration</h3>
          <div className="flex gap-2">
            {([
              { value: 60, label: '1 min' },
              { value: 90, label: '1.5 min' },
              { value: 120, label: '2 min' },
              { value: 150, label: '2.5 min' },
              { value: 180, label: '3 min' },
            ]).map((opt) => (
              <button
                key={opt.value}
                onClick={() => setTargetDuration(opt.value)}
                className={cn(
                  "flex-1 py-2 rounded-lg border text-sm font-medium transition-all cursor-pointer",
                  targetDuration === opt.value
                    ? "border-accent bg-accent/10 text-accent-dark"
                    : "border-border bg-card text-muted-foreground hover:border-accent/40 hover:text-foreground"
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <ErrorDisplay error={error} />

      {videoUrl && (
        <div className="space-y-3">
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={generateThumbnail}
              onChange={(e) => setGenerateThumbnail(e.target.checked)}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Generate thumbnail title card
              </span>
              <p className="text-xs text-muted-foreground">
                AI-generated cinematic intro image at the start of the promo
              </p>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer group">
            <input
              type="checkbox"
              checked={textOverlay}
              onChange={(e) => setTextOverlay(e.target.checked)}
              className="w-4 h-4 rounded border-border text-accent focus:ring-accent/30 cursor-pointer"
            />
            <div>
              <span className="text-sm font-medium text-foreground group-hover:text-accent-dark transition-colors">
                Bold text overlays
              </span>
              <p className="text-xs text-muted-foreground">
                AI-generated stylized text on each segment (ESPN / Netflix style)
              </p>
            </div>
          </label>
        </div>
      )}

      <div className="flex justify-end">
        <Button
          icon={Scissors}
          onClick={handleGeneratePromo}
          disabled={!gcsUri || submitting}
          className={cn(submitting && "[&_svg]:animate-spin")}
        >
          {submitting ? 'Starting...' : 'Generate Promo'}
        </Button>
      </div>
    </div>
  )
}
