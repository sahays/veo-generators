import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Smartphone, RectangleVertical } from 'lucide-react'
import { Button } from '@/components/Common'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/hooks/useApiClient'
import { cn } from '@/lib/utils'
import { usePolling } from '@/hooks/usePolling'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { buildStatusConfig } from '@/hooks/jobStatus'
import { reframeCreateSchema } from '@/types/schemas'
import { VideoSourceSelector } from '@/components/shared/VideoSourceSelector'
import { ReframeCompleted } from '@/components/pages/reframe/components/ReframeCompleted'
import { ReframePipelineLinks } from '@/components/pages/reframe/components/ReframePipelineLinks'
import {
  WorkViewShell,
  WorkCreateShell,
  SelectedVideoPreview,
  CheckboxOption,
} from '@/components/shared/WorkPageShell'
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

const FORMAT_OPTIONS = [
  {
    id: '9:16' as const,
    label: 'Adaptive 9:16',
    icon: Smartphone,
    desc: 'Each scene picks its own aspect ratio on a 9:16 canvas',
  },
  {
    id: '3:4' as const,
    label: 'Adaptive 3:4',
    icon: RectangleVertical,
    desc: 'Each scene picks its own aspect ratio on a 3:4 canvas',
  },
]

const ReframeViewSection = ({ id }: { id: string }) => {
  const { record, loading: recordLoading, error: pollError } = usePolling(id, api.reframe.get, ACTIVE_STATUSES)
  const badge = record?.blurred_bg ? (
    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-purple-500/10 text-purple-600 border border-purple-500/20">Blurred BG</span>
  ) : undefined
  return (
    <WorkViewShell backPath="/orientations" backLabel="Back to Orientations" defaultName="Reframe" loadingLabel="Loading reframe..." record={record} loading={recordLoading} pollError={pollError} statusConfig={STATUS_CONFIG} activeStatuses={ACTIVE_STATUSES} onSaveName={(name) => api.reframe.update(record!.id, { display_name: name })} onRetry={() => api.reframe.retry(id)} headerBadges={badge}>
      {(rec) => (
        <>
          <ReframePipelineLinks recordId={rec.id} hasPlan={!!((rec.segment_plan as unknown[] | undefined)?.length) || !!rec.eval_report} />
          {rec.status === 'completed' && <ReframeCompleted record={rec} />}
        </>
      )}
    </WorkViewShell>
  )
}

const ReframeFormatOptions = ({
  outputAspectRatio,
  setOutputAspectRatio,
  diagnosticMode,
  setDiagnosticMode,
}: {
  outputAspectRatio: '9:16' | '3:4'
  setOutputAspectRatio: (v: '9:16' | '3:4') => void
  diagnosticMode: boolean
  setDiagnosticMode: (v: boolean) => void
}) => (
  <div className="space-y-3">
    <div className="space-y-2">
      <span className="text-sm font-medium text-foreground">Output format</span>
      <div className="flex gap-3">
        {FORMAT_OPTIONS.map((opt) => (
          <Button
            key={opt.id}
            variant="unstyled"
            onClick={() => setOutputAspectRatio(opt.id)}
            className={cn(
              'flex-1 flex flex-col items-center gap-1.5 p-3 rounded-[6px] border transition-all text-center',
              outputAspectRatio === opt.id ? 'bg-accent/10 border-accent text-accent-dark' : 'border-border text-muted-foreground hover:border-accent/30',
            )}
          >
            <opt.icon size={20} />
            <span className="text-[11px] font-bold uppercase tracking-widest">{opt.label}</span>
            <span className="text-[10px] text-muted-foreground leading-tight">{opt.desc}</span>
          </Button>
        ))}
      </div>
    </div>
    <CheckboxOption
      checked={diagnosticMode}
      onChange={setDiagnosticMode}
      label="Diagnostic preview"
      description={`Skip cropping — render the full frame letterboxed in ${outputAspectRatio} with detected faces and scene labels drawn on top, to see what the models see`}
    />
  </div>
)

function useReframeSubmit(params: {
  gcsUri: string | null
  videoFilename: string
  diagnosticMode: boolean
  outputAspectRatio: '9:16' | '3:4'
  modelConfig: { modelId?: string; region?: string }
}) {
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleStartReframe = async () => {
    const parsed = reframeCreateSchema.safeParse({
      gcs_uri: params.gcsUri || '',
      source_filename: params.videoFilename || 'Untitled',
      diagnostic_mode: params.diagnosticMode,
      output_aspect_ratio: params.outputAspectRatio,
      model_id: params.modelConfig.modelId,
      region: params.modelConfig.region,
    })
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message || 'Invalid reframe parameters')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const result = await api.reframe.create(parsed.data)
      navigate(`/orientations/${result.id}`, { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Reframe failed')
    } finally {
      setSubmitting(false)
    }
  }

  return { submitting, error, handleStartReframe }
}

const ReframeCreateSection = () => {
  const { sourceTab, setSourceTab, videoUrl, gcsUri, videoFilename, productions, uploads, loading: loadingSources, select } = useVideoSourceState<UploadItem, ProductionItem>(
    { loadUploads: () => api.reframe.listUploadSources(), loadProductions: () => api.reframe.listProductionSources().then((prods) => prods.filter((p: ProductionItem) => p.orientation === '16:9')) },
    { enabled: true },
  )
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [diagnosticMode, setDiagnosticMode] = useState(false)
  const [outputAspectRatio, setOutputAspectRatio] = useState<'9:16' | '3:4'>('9:16')
  const { submitting, error, handleStartReframe } = useReframeSubmit({ gcsUri, videoFilename, diagnosticMode, outputAspectRatio, modelConfig })

  return (
    <WorkCreateShell backPath="/orientations" backLabel="Back to Orientations" title="New Reframe" subtitle="Select a landscape (16:9) video to reframe to portrait (9:16 or 3:4)" error={error} actionIcon={Smartphone} actionLabel="Start Reframe" submitting={submitting} disabled={!gcsUri} onSubmit={handleStartReframe} actionLeft={<ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />}>
      <VideoSourceSelector uploads={uploads} productions={productions} loading={loadingSources} sourceTab={sourceTab} onTabChange={setSourceTab} selectedUri={gcsUri} onSelectUpload={(u) => select(u.video_signed_url, u.gcs_uri, u.display_name || u.filename)} onSelectProduction={(p) => select(p.video_signed_url, p.final_video_url, p.name)} emptyProductionsMessage="No completed 16:9 productions found." />
      <SelectedVideoPreview videoUrl={videoUrl} videoFilename={videoFilename} />
      {videoUrl && <ReframeFormatOptions outputAspectRatio={outputAspectRatio} setOutputAspectRatio={setOutputAspectRatio} diagnosticMode={diagnosticMode} setDiagnosticMode={setDiagnosticMode} />}
    </WorkCreateShell>
  )
}

export const ReframeWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  return id ? <ReframeViewSection id={id} /> : <ReframeCreateSection />
}
