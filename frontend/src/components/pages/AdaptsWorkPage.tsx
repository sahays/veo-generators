import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  LayoutGrid, Loader2, ArrowLeft, Download, RotateCcw,
  AlertCircle, CheckCircle2, ExternalLink,
} from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/store/useAuthStore'
import { usePolling } from '@/hooks/usePolling'
import { ImageSourceSelector } from '@/components/shared/ImageSourceSelector'
import { AspectRatioSelector } from '@/components/shared/AspectRatioSelector'
import { ProgressBar } from '@/components/shared/ProgressBar'
import { ErrorDisplay } from '@/components/shared/ErrorDisplay'
import { WorkPageHeader } from '@/components/shared/WorkPageHeader'
import type { ImageUploadItem } from '@/components/shared/ImageSourceSelector'
import type { AdaptRecord, PresetBundle } from '@/types/project'

const ACTIVE_STATUSES = ['pending', 'generating']

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  pending: { label: 'Waiting to start...', color: 'text-amber-500' },
  generating: { label: 'Generating variants...', color: 'text-blue-500' },
  completed: { label: 'All variants complete', color: 'text-emerald-500' },
  partial: { label: 'Some variants failed', color: 'text-orange-500' },
  failed: { label: 'Generation failed', color: 'text-red-500' },
}

export const AdaptsWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  useAuthStore()
  const isViewMode = !!id

  // Image source state
  const [images, setImages] = useState<ImageUploadItem[]>([])
  const [loadingSources, setLoadingSources] = useState(false)
  const [selectedImage, setSelectedImage] = useState<ImageUploadItem | null>(null)

  // Template state
  const [templateImage, setTemplateImage] = useState<ImageUploadItem | null>(null)
  const [showTemplateSelector, setShowTemplateSelector] = useState(false)

  // Aspect ratio state
  const [selectedRatios, setSelectedRatios] = useState<string[]>([])
  const [presets, setPresets] = useState<Record<string, PresetBundle>>({})

  // Processing state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // View mode polling
  const { record, loading: recordLoading, error: pollError } = usePolling<AdaptRecord>(
    id,
    api.adapts.get,
    ACTIVE_STATUSES,
  )

  // Load sources and presets for create mode
  useEffect(() => {
    if (isViewMode) return
    setLoadingSources(true)
    Promise.all([
      api.adapts.listUploadSources().catch(() => []),
      api.adapts.listPresets().catch(() => ({ presets: {}, all_ratios: [] })),
    ]).then(([imgs, presetsData]) => {
      setImages(imgs)
      setPresets(presetsData.presets || {})
    }).finally(() => setLoadingSources(false))
  }, [isViewMode])

  const handleGenerate = async () => {
    if (!selectedImage || selectedRatios.length === 0) return
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.adapts.create({
        gcs_uri: selectedImage.gcs_uri,
        source_filename: selectedImage.display_name || selectedImage.filename,
        source_mime_type: selectedImage.mime_type,
        template_gcs_uri: templateImage?.gcs_uri || undefined,
        aspect_ratios: selectedRatios,
      })
      navigate(`/adapts/${result.id}`, { replace: true })
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
      await api.adapts.retry(id)
    } catch (err: any) {
      console.error('Failed to retry adapt', err)
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
          <p className="text-sm text-muted-foreground">Loading adapt...</p>
        </div>
      )
    }

    if (pollError && !record) {
      return (
        <div className="space-y-4">
          <button onClick={() => navigate('/adapts')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
            <ArrowLeft size={16} /> Back to Adapts
          </button>
          <ErrorDisplay error={pollError} size="md" />
        </div>
      )
    }

    if (!record) return null

    const isProcessing = ACTIVE_STATUSES.includes(record.status)
    const completedVariants = record.variants.filter(v => v.status === 'completed')
    const failedVariants = record.variants.filter(v => v.status === 'failed')

    return (
      <div className="space-y-6">
        <WorkPageHeader
          backPath="/adapts"
          backLabel="Back to Adapts"
          record={record}
          defaultName="Adapt"
          onSaveName={(name) => api.adapts.update(record.id, { display_name: name })}
          statusConfig={STATUS_CONFIG}
          activeStatuses={ACTIVE_STATUSES}
        >
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-slate-500/10 text-slate-600 border border-slate-500/20">
            {record.variants.length} variant{record.variants.length !== 1 ? 's' : ''}
          </span>
          {record.preset_bundle && (
            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-amber-500/10 text-amber-600 border border-amber-500/20 capitalize">
              {record.preset_bundle}
            </span>
          )}
          {completedVariants.some(v => v.prompt_text_used) && (
            <Link
              to={`/adapts/${record.id}/prompt`}
              target="_blank"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
            >
              Prompt <ExternalLink size={12} />
            </Link>
          )}
        </WorkPageHeader>

        {isProcessing && <ProgressBar progress={record.progress_pct} />}

        {record.status === 'failed' && (
          <div className="space-y-3">
            {record.error_message && <ErrorDisplay error={record.error_message} size="md" />}
            <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetry} disabled={retrying}>
              {retrying ? 'Retrying...' : 'Retry'}
            </Button>
          </div>
        )}

        {record.status === 'partial' && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-orange-600">
              <AlertCircle size={16} />
              {failedVariants.length} variant{failedVariants.length !== 1 ? 's' : ''} failed
            </div>
            <Button icon={retrying ? Loader2 : RotateCcw} onClick={handleRetry} disabled={retrying}>
              {retrying ? 'Retrying...' : 'Retry Failed'}
            </Button>
          </div>
        )}

        {/* Source image preview */}
        {record.source_signed_url && (
          <div className="space-y-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Source Image</h3>
            <img
              src={record.source_signed_url}
              alt="Source"
              className="rounded-xl border border-border max-w-sm"
            />
          </div>
        )}

        {/* Variant grid */}
        {record.variants.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Variants ({completedVariants.length}/{record.variants.length})
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {record.variants.map((variant, i) => (
                <div
                  key={i}
                  className="glass bg-card rounded-xl border border-border overflow-hidden"
                >
                  {variant.status === 'completed' && variant.output_signed_url ? (
                    <div className="bg-muted/30 flex items-center justify-center p-3">
                      <img
                        src={variant.output_signed_url}
                        alt={`${variant.aspect_ratio} variant`}
                        className="max-w-full max-h-64 rounded-lg object-contain"
                      />
                    </div>
                  ) : variant.status === 'failed' ? (
                    <div className="aspect-video bg-red-500/5 flex items-center justify-center">
                      <AlertCircle size={24} className="text-red-400" />
                    </div>
                  ) : (
                    <div className="aspect-video bg-muted/30 flex items-center justify-center">
                      <Loader2 size={24} className="animate-spin text-muted-foreground" />
                    </div>
                  )}
                  <div className="p-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-heading font-bold text-foreground">
                        {variant.aspect_ratio}
                      </span>
                      {variant.status === 'completed' && (
                        <CheckCircle2 size={14} className="text-emerald-500" />
                      )}
                      {variant.status === 'failed' && (
                        <AlertCircle size={14} className="text-red-500" />
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {variant.status === 'completed' && variant.prompt_text_used && (
                        <Link
                          to={`/adapts/${record.id}/prompt/${i}`}
                          target="_blank"
                          className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                          title="View prompt"
                        >
                          <ExternalLink size={14} />
                        </Link>
                      )}
                      {variant.status === 'completed' && variant.output_signed_url && (
                        <a
                          href={variant.output_signed_url}
                          download
                          target="_blank"
                          rel="noopener noreferrer"
                          className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                          title="Download"
                        >
                          <Download size={14} />
                        </a>
                      )}
                    </div>
                  </div>
                  {variant.status === 'failed' && variant.error_message && (
                    <p className="px-3 pb-3 text-[10px] text-red-500 line-clamp-2">
                      {variant.error_message}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {record.usage && record.usage.cost_usd > 0 && (
          <div className="text-xs text-muted-foreground">
            AI cost: ${record.usage.cost_usd.toFixed(4)} ({record.usage.image_generations} image{record.usage.image_generations !== 1 ? 's' : ''})
          </div>
        )}
      </div>
    )
  }

  // --- Create Mode ---
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={() => navigate('/adapts')} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Adapts
        </button>
      </div>

      <div className="space-y-1">
        <h2 className="text-lg font-heading font-bold text-foreground">New Adapt</h2>
        <p className="text-sm text-muted-foreground">Select an image and choose aspect ratios to generate adapted versions</p>
      </div>

      <div className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Source Image</h3>
        <ImageSourceSelector
          images={images}
          loading={loadingSources}
          selectedUri={selectedImage?.gcs_uri ?? null}
          onSelect={setSelectedImage}
        />
      </div>

      {selectedImage && (
        <div className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Selected</h3>
          <div className="flex items-start gap-4">
            <img
              src={selectedImage.image_signed_url}
              alt={selectedImage.display_name || selectedImage.filename}
              className="w-32 h-32 object-cover rounded-lg border border-border"
            />
            <div>
              <p className="text-sm font-medium text-foreground">{selectedImage.display_name || selectedImage.filename}</p>
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
            <button
              onClick={() => setShowTemplateSelector(!showTemplateSelector)}
              className="text-xs text-accent hover:text-accent-dark transition-colors"
            >
              {showTemplateSelector ? 'Hide' : templateImage ? 'Change' : 'Add template'}
            </button>
          </div>
          {templateImage && !showTemplateSelector && (
            <div className="flex items-center gap-3 p-2 rounded-lg border border-border bg-card">
              <img
                src={templateImage.image_signed_url}
                alt="Template"
                className="w-12 h-12 object-cover rounded"
              />
              <span className="text-sm text-foreground truncate">{templateImage.display_name || templateImage.filename}</span>
              <button
                onClick={() => setTemplateImage(null)}
                className="ml-auto text-xs text-muted-foreground hover:text-red-500 transition-colors"
              >
                Remove
              </button>
            </div>
          )}
          {showTemplateSelector && (
            <ImageSourceSelector
              images={images.filter(img => img.gcs_uri !== selectedImage.gcs_uri)}
              loading={false}
              selectedUri={templateImage?.gcs_uri ?? null}
              onSelect={(img) => { setTemplateImage(img); setShowTemplateSelector(false) }}
              emptyMessage="No other images available for template."
            />
          )}
        </div>
      )}

      {selectedImage && (
        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Aspect Ratios</h3>
          <AspectRatioSelector
            selected={selectedRatios}
            onChange={setSelectedRatios}
            presets={presets}
          />
        </div>
      )}

      <ErrorDisplay error={error} />

      <div className="flex justify-end">
        <Button
          icon={LayoutGrid}
          onClick={handleGenerate}
          disabled={!selectedImage || selectedRatios.length === 0 || submitting}
          className={cn(submitting && "[&_svg]:animate-spin")}
        >
          {submitting ? 'Starting...' : `Generate ${selectedRatios.length} Variant${selectedRatios.length !== 1 ? 's' : ''}`}
        </Button>
      </div>
    </div>
  )
}
