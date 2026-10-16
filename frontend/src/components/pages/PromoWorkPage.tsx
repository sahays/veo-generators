import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Scissors } from 'lucide-react'
import { Button } from '@/components/Common'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { PromoCompleted } from '@/components/pages/promo/PromoCompleted'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { ModelPill } from '@/components/ModelPill'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { promoCreateSchema } from '@/types/schemas'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { PromptSelector } from '@/components/shared/PromptSelector'
import {
  WorkViewShell,
  WorkCreateShell,
  SelectedVideoPreview,
  CheckboxOption,
} from '@/components/shared/WorkPageShell'
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
  const isViewMode = !!id

  const {
    sourceTab,
    setSourceTab,
    videoUrl,
    gcsUri,
    videoFilename,
    productions,
    uploads,
    loading: loadingSources,
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
    api.system
      .listResources('prompt', 'promo')
      .catch(() => [])
      .then((promoPrompts) => {
        setPrompts(promoPrompts)
        const active = promoPrompts.find((p: SystemResource) => p.is_active)
        if (active) setPromptId(active.id)
      })
  }, [isViewMode])

  const handleGeneratePromo = async () => {
    const parsed = promoCreateSchema.safeParse({
      gcs_uri: gcsUri || '',
      source_filename: videoFilename || 'Untitled',
      prompt_id: promptId || undefined,
      target_duration: targetDuration,
      text_overlay: textOverlay,
      generate_thumbnail: generateThumbnail,
      model_id: modelConfig.modelId,
      region: modelConfig.region,
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message || 'Invalid promo parameters')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.promo.create(parsed.data)
      navigate(`/promos/${result.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (isViewMode) {
    return (
      <WorkViewShell
        backPath="/promos"
        backLabel="Back to Promos"
        defaultName="Promo"
        loadingLabel="Loading promo..."
        record={record}
        loading={recordLoading}
        pollError={pollError}
        statusConfig={STATUS_CONFIG}
        activeStatuses={ACTIVE_STATUSES}
        onSaveName={(name) => api.promo.update(record!.id, { display_name: name })}
        onRetry={id ? () => api.promo.retry(id) : undefined}
        headerBadges={
          record ? (
            <>
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
            </>
          ) : undefined
        }
      >
        {(rec) => <>{rec.status === 'completed' && <PromoCompleted record={rec} />}</>}
      </WorkViewShell>
    )
  }

  return (
    <WorkCreateShell
      backPath="/promos"
      backLabel="Back to Promos"
      title="New Promo"
      subtitle="Select a video to generate a promotional highlight reel"
      error={error}
      actionIcon={Scissors}
      actionLabel="Generate Promo"
      submitting={submitting}
      disabled={!gcsUri}
      onSubmit={handleGeneratePromo}
      actionLeft={
        <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />
      }
      footerExtra={id ? <ServicesUsedPanel feature="promo" recordId={id} /> : undefined}
    >
      <VideoSourceSelector
        uploads={uploads}
        productions={productions}
        loading={loadingSources}
        sourceTab={sourceTab}
        onTabChange={setSourceTab}
        selectedUri={gcsUri}
        onSelectUpload={(u) =>
          select(u.video_signed_url, u.gcs_uri, u.display_name || u.filename)
        }
        onSelectProduction={(p) =>
          select(p.video_signed_url, p.final_video_url, p.name)
        }
      />

      <SelectedVideoPreview videoUrl={videoUrl} videoFilename={videoFilename} />

      {videoUrl && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Promo Prompt
          </h3>
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
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Target Duration
          </h3>
          <div className="flex gap-2">
            {[
              { value: 60, label: '1 min' },
              { value: 90, label: '1.5 min' },
              { value: 120, label: '2 min' },
              { value: 150, label: '2.5 min' },
              { value: 180, label: '3 min' },
            ].map((opt) => (
              <Button
                key={opt.value}
                variant="unstyled"
                onClick={() => setTargetDuration(opt.value)}
                className={cn(
                  'flex-1 py-2 rounded-[5px] border text-sm font-medium transition-all',
                  targetDuration === opt.value
                    ? 'border-accent bg-accent/10 text-accent-dark'
                    : 'border-border bg-card text-muted-foreground hover:border-accent/40 hover:text-foreground',
                )}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        </div>
      )}

      {videoUrl && (
        <div className="space-y-2">
          <CheckboxOption
            checked={generateThumbnail}
            onChange={setGenerateThumbnail}
            label="Generate thumbnail title card"
            description="AI-generated cinematic intro image at the start of the promo"
          />
          <CheckboxOption
            checked={textOverlay}
            onChange={setTextOverlay}
            label="Bold text overlays"
            description="AI-generated stylized text on each segment (ESPN / Netflix style)"
          />
        </div>
      )}
    </WorkCreateShell>
  )
}
