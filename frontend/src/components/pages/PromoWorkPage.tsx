import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import {
  Scissors, Loader2, ArrowLeft, RotateCcw,
} from 'lucide-react'
import { Button } from '@/components/Common'
import { PromoCompleted } from '@/components/pages/promo/PromoCompleted'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/useAuthStore'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { PromptSelector } from '@/components/shared/PromptSelector'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { WorkPageHeader } from '@/components/shared/WorkPageHeader'
import { ModelPill } from '@/components/ModelPill'
import type { UploadItem, ProductionItem } from '@/components/shared/VideoSourceSelector'
import type { SystemResource } from '@/types/project'

const ACTIVE_STATUSES = ['pending', 'analyzing', 'extracting', 'stitching', 'encoding']

const STATUS_CONFIG = buildStatusConfig(
  {
    pending: { label: 'Preparing to analyze...', color: 'text-amber-500' },
    analyzing: { label: 'Analyzing video with AI...', color: 'text-amber-500' },
    extracting: { label: 'Extracting best moments...', color: 'text-blue-500' },
    stitching: { label: 'Stitching promo together...', color: 'text-indigo-500' },
    encoding: { label: 'Encoding final output...', color: 'text-purple-500' },
  },
  {
    completed: { label: 'Promo complete', color: 'text-emerald-500' },
    failed: { label: 'Promo generation failed', color: 'text-red-500' },
  },
)

export const PromoWorkPage = () => {
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
      loadUploads: () => api.promo.listUploadSources(),
      loadProductions: () => api.promo.listProductionSources(),
    },
    { enabled: !isViewMode },
  )

  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [targetDuration, setTargetDuration] = useState(60)
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')
  const [textOverlay, setTextOverlay] = useState(false)
  const [generateThumbnail, setGenerateThumbnail] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { record, loading: recordLoading, error: pollError } = usePolling(
    id,
    api.promo.get,
    ACTIVE_STATUSES,
  )

  useEffect(() => {
    if (isViewMode) return
    api.system.listResources('prompt', 'promo').catch(() => []).then((promoPrompts) => {
      setPrompts(promoPrompts)
      const active = promoPrompts.find((p: SystemResource) => p.is_active)
      if (active) setPromptId(active.id)
    })
  }, [isViewMode])

  const handleSelectUpload = (upload: UploadItem) =>
    select(upload.video_signed_url, upload.gcs_uri, upload.display_name || upload.filename)

  const handleSelectProduction = (prod: ProductionItem) =>
    select(prod.video_signed_url, prod.final_video_url, prod.name)

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
        model_id: modelConfig.modelId,
        region: modelConfig.region,
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

    const isProcessing = ACTIVE_STATUSES.includes(record.status)

    return (
      <div className="space-y-6">
        <WorkPageHeader
          backPath="/promos"
          backLabel="Back to Promos"
          record={record}
          defaultName="Promo"
          onSaveName={(name) => api.promo.update(record.id, { display_name: name })}
          statusConfig={STATUS_CONFIG}
          activeStatuses={ACTIVE_STATUSES}
        >
          <ModelPill modelName={record.usage?.model_name} />
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

        {record.status === 'completed' && <PromoCompleted record={record} />}
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

      <div className="flex items-center justify-end gap-4">
        <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} className="mt-2" />
        <Button
          icon={Scissors}
          onClick={handleGeneratePromo}
          disabled={!gcsUri || submitting}
          className={cn(submitting && "[&_svg]:animate-spin")}
        >
          {submitting ? 'Starting...' : 'Generate Promo'}
        </Button>
      </div>

      {id && <ServicesUsedPanel feature="promo" recordId={id} />}
    </div>
  )
}
