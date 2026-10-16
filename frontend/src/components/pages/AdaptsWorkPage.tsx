import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { LayoutGrid, AlertCircle, ExternalLink } from 'lucide-react'
import { Button } from '@/components/Common'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/lib/api'
import { usePolling } from '@/hooks/usePolling'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { adaptCreateSchema } from '@/types/schemas'
import { ImageSourceSelector } from '@/components/shared/ImageSourceSelector'
import { AdaptVariantGrid } from '@/components/pages/adapts/AdaptVariantGrid'
import { AspectRatioSelector } from '@/components/shared/AspectRatioSelector'
import { WorkViewShell, WorkCreateShell } from '@/components/shared/WorkPageShell'
import type { ImageUploadItem } from '@/components/shared/ImageSourceSelector'
import type { AdaptRecord, PresetBundle } from '@/types/project'

const ACTIVE_STATUSES = ['pending', 'generating']

const STATUS_CONFIG = buildStatusConfig(
  {
    pending: { label: 'Waiting to start...', color: 'text-amber-500' },
    generating: { label: 'Generating variants...', color: 'text-blue-500' },
    partial: { label: 'Some variants failed', color: 'text-orange-500' },
  },
  {
    completed: { label: 'All variants complete', color: 'text-emerald-500' },
    failed: { label: 'Generation failed', color: 'text-red-500' },
  },
)

export const AdaptsWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isViewMode = !!id

  const [images, setImages] = useState<ImageUploadItem[]>([])
  const [loadingSources, setLoadingSources] = useState(false)
  const [selectedImage, setSelectedImage] = useState<ImageUploadItem | null>(null)

  const [templateImage, setTemplateImage] = useState<ImageUploadItem | null>(null)
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)

  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [selectedRatios, setSelectedRatios] = useState<string[]>([])
  const [presets, setPresets] = useState<Record<string, PresetBundle>>({})

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { record, loading: recordLoading, error: pollError } = usePolling<AdaptRecord>(
    id,
    api.adapts.get,
    ACTIVE_STATUSES,
  )

  useEffect(() => {
    if (isViewMode) return
    setLoadingSources(true)
    Promise.all([
      api.adapts.listUploadSources().catch(() => []),
      api.adapts.listPresets().catch(() => ({ presets: {}, all_ratios: [] })),
    ])
      .then(([imgs, presetsData]) => {
        setImages(imgs)
        setPresets(presetsData.presets || {})
      })
      .finally(() => setLoadingSources(false))
  }, [isViewMode])

  const handleGenerate = async () => {
    const parsed = adaptCreateSchema.safeParse({
      gcs_uri: selectedImage?.gcs_uri || '',
      source_filename: selectedImage?.display_name || selectedImage?.filename || '',
      source_mime_type: selectedImage?.mime_type || '',
      template_gcs_uri: templateImage?.gcs_uri || undefined,
      aspect_ratios: selectedRatios,
      model_id: modelConfig.modelId,
      region: modelConfig.region,
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message || 'Invalid adapt parameters')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.adapts.create(parsed.data)
      navigate(`/adapts/${result.id}`, { replace: true })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (isViewMode) {
    const completedVariants =
      record?.variants.filter((v) => v.status === 'completed') || []
    const failedVariants =
      record?.variants.filter((v) => v.status === 'failed') || []

    return (
      <WorkViewShell
        backPath="/adapts"
        backLabel="Back to Adapts"
        defaultName="Adapt"
        loadingLabel="Loading adapt..."
        record={record}
        loading={recordLoading}
        pollError={pollError}
        statusConfig={STATUS_CONFIG}
        activeStatuses={ACTIVE_STATUSES}
        onSaveName={(name) => api.adapts.update(record!.id, { display_name: name })}
        onRetry={id ? () => api.adapts.retry(id) : undefined}
        retryLabel={record?.status === 'partial' ? 'Retry Failed' : 'Retry'}
        retryStatuses={['failed', 'partial']}
        headerBadges={
          record ? (
            <>
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-slate-500/10 text-slate-600 border border-slate-500/20">
                {record.variants.length} variant{record.variants.length !== 1 ? 's' : ''}
              </span>
              {record.preset_bundle && (
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-600 border border-amber-500/20 capitalize">
                  {record.preset_bundle}
                </span>
              )}
              {completedVariants.some((v) => v.prompt_text_used) && (
                <Button asChild variant="outline" size="xs">
                  <Link to={`/adapts/${record.id}/prompt`} target="_blank">
                    Prompt <ExternalLink size={12} />
                  </Link>
                </Button>
              )}
            </>
          ) : undefined
        }
      >
        {(rec) => (
          <>
            {rec.status === 'partial' && (
              <div className="flex items-center gap-2 text-sm text-orange-600">
                <AlertCircle size={16} />
                {failedVariants.length} variant{failedVariants.length !== 1 ? 's' : ''} failed
              </div>
            )}

            {rec.source_signed_url && (
              <div className="space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Source Image
                </h3>
                <img
                  src={rec.source_signed_url}
                  alt="Source"
                  className="rounded-xl border border-border max-w-sm"
                />
              </div>
            )}

            <AdaptVariantGrid recordId={rec.id} variants={rec.variants} />

            {rec.usage && rec.usage.cost_usd > 0 && (
              <div className="text-xs text-muted-foreground">
                AI cost: ${rec.usage.cost_usd.toFixed(4)} ({rec.usage.image_generations}{' '}
                image{rec.usage.image_generations !== 1 ? 's' : ''})
              </div>
            )}
          </>
        )}
      </WorkViewShell>
    )
  }

  return (
    <WorkCreateShell
      backPath="/adapts"
      backLabel="Back to Adapts"
      title="New Adapt"
      subtitle="Select an image and choose aspect ratios to generate adapted versions"
      error={error}
      actionIcon={LayoutGrid}
      actionLabel={`Generate ${selectedRatios.length} Variant${selectedRatios.length !== 1 ? 's' : ''}`}
      submitting={submitting}
      disabled={!selectedImage || selectedRatios.length === 0}
      onSubmit={handleGenerate}
      actionLeft={
        <ModelRegionPicker capability="image" value={modelConfig} onChange={setModelConfig} />
      }
    >
      <div className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Source Image
        </h3>
        <ImageSourceSelector
          images={images}
          loading={loadingSources}
          selectedUri={selectedImage?.gcs_uri ?? null}
          onSelect={setSelectedImage}
        />
      </div>

      {selectedImage && (
        <div className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Selected
          </h3>
          <div className="flex items-start gap-4">
            <img
              src={selectedImage.image_signed_url}
              alt={selectedImage.display_name || selectedImage.filename}
              className="w-32 h-32 object-cover rounded-lg border border-border"
            />
            <div>
              <p className="text-sm font-medium text-foreground">
                {selectedImage.display_name || selectedImage.filename}
              </p>
              <p className="text-xs text-muted-foreground">{selectedImage.mime_type}</p>
            </div>
          </div>
        </div>
      )}

      {selectedImage && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Layout Template (Optional)
            </h3>
            <Button
              variant="link"
              onClick={() => setShowTemplateSelector(!showTemplateSelector)}
              className="text-xs text-accent hover:text-accent-dark"
            >
              {showTemplateSelector ? 'Hide' : templateImage ? 'Change' : 'Add template'}
            </Button>
          </div>
          {templateImage && !showTemplateSelector && (
            <div className="flex items-center gap-3 p-2 rounded-[6px] border border-border bg-card">
              <img
                src={templateImage.image_signed_url}
                alt="Template"
                className="w-12 h-12 object-cover rounded"
              />
              <span className="text-sm text-foreground truncate">
                {templateImage.display_name || templateImage.filename}
              </span>
              <Button
                variant="link"
                onClick={() => setTemplateImage(null)}
                className="ml-auto text-xs text-muted-foreground hover:text-red-500"
              >
                Remove
              </Button>
            </div>
          )}
          {showTemplateSelector && (
            <ImageSourceSelector
              images={images.filter((img) => img.gcs_uri !== selectedImage.gcs_uri)}
              loading={false}
              selectedUri={templateImage?.gcs_uri ?? null}
              onSelect={(img) => {
                setTemplateImage(img)
                setShowTemplateSelector(false)
              }}
              emptyMessage="No other images available for template."
            />
          )}
        </div>
      )}

      {selectedImage && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
            Aspect Ratios
          </h3>
          <AspectRatioSelector
            selected={selectedRatios}
            onChange={setSelectedRatios}
            presets={presets}
          />
        </div>
      )}
    </WorkCreateShell>
  )
}
