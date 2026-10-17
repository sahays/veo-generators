import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/hooks/useApiClient'
import { useAuthStore } from '@/store/useAuthStore'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { ThumbnailsSourcePicker } from '@/components/pages/thumbnails/components/ThumbnailsSourcePicker'
import {
  mapMomentsToScreenshots,
  runScreenshotCapture,
  ThumbnailAnalyzeControls,
  ThumbnailOutputSections,
  ThumbnailsPageHeader,
  type AnalyzeMomentInput,
  type ScreenshotWithLocal,
} from '@/components/pages/thumbnails/ThumbnailsWorkSections'
import type {
  ThumbnailRecord,
  SystemResource,
  CompletedProductionSource,
  UploadRecord,
} from '@/types/project'

type ThumbnailRecordWithUsage = ThumbnailRecord & { usage?: { model_name?: string } }

function useThumbnailPrompts() {
  const [analysisPrompts, setAnalysisPrompts] = useState<SystemResource[]>([])
  const [analysisPromptId, setAnalysisPromptId] = useState('')
  const [collagePrompts, setCollagePrompts] = useState<SystemResource[]>([])
  const [collagePromptId, setCollagePromptId] = useState('')

  useEffect(() => {
    api.system.listResources('prompt', 'thumbnails').then(setAnalysisPrompts).catch(() => {})
    api.system.listResources('prompt', 'collage').then(setCollagePrompts).catch(() => {})
  }, [])

  return {
    analysisPrompts, analysisPromptId, setAnalysisPromptId,
    collagePrompts, collagePromptId, setCollagePromptId,
  }
}

function useThumbnailRecordState(
  id: string | undefined,
  select: (url: string | null, gcs: string | null, name: string) => void,
) {
  const [videoSource, setVideoSource] = useState<'upload' | 'production'>('upload')
  const [productionId, setProductionId] = useState<string | undefined>()
  const [screenshots, setScreenshots] = useState<ScreenshotWithLocal[]>([])
  const [videoSummary, setVideoSummary] = useState<string | null>(null)
  const [recordId, setRecordId] = useState<string | null>(id || null)
  const [error, setError] = useState<string | null>(null)
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null)
  const [recordStatus, setRecordStatus] = useState<string>('analyzing')
  const [modelName, setModelName] = useState<string | undefined>()
  const [loadingRecord, setLoadingRecord] = useState(false)
  const justCreatedRef = useRef(false)

  useEffect(() => {
    if (!id) return
    if (justCreatedRef.current) {
      justCreatedRef.current = false
      return
    }
    setLoadingRecord(true)
    api.thumbnails
      .get(id)
      .then((rec: ThumbnailRecordWithUsage) => {
        select(rec.video_signed_url || null, rec.video_gcs_uri, rec.display_name || rec.video_filename)
        setVideoSource(rec.video_source)
        setProductionId(rec.production_id)
        setVideoSummary(rec.video_summary || null)
        setModelName(rec.usage?.model_name)
        setScreenshots(rec.screenshots.map((s) => ({ ...s, localUrl: s.signed_url })))
        setRecordId(rec.id)
        setRecordStatus(rec.status)
        if (rec.thumbnail_signed_url) setThumbnailUrl(rec.thumbnail_signed_url)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load record'))
      .finally(() => setLoadingRecord(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  return {
    videoSource, setVideoSource, productionId, setProductionId,
    screenshots, setScreenshots, videoSummary, setVideoSummary,
    recordId, setRecordId, error, setError, thumbnailUrl, setThumbnailUrl,
    recordStatus, setRecordStatus, modelName, loadingRecord, justCreatedRef,
  }
}

function useThumbnailCaptureState(id: string | undefined, canWrite: boolean, recState: ReturnType<typeof useThumbnailRecordState>) {
  const [capturing, setCapturing] = useState(false)
  const [captureProgress, setCaptureProgress] = useState(0)
  const [videoReady, setVideoReady] = useState(false)
  const captureStartedRef = useRef(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const captureScreenshots = async (rid: string, moments: { timestamp_start: string; timestamp_end: string }[]) =>
    runScreenshotCapture({ video: videoRef.current, canvas: canvasRef.current, rid, moments, setCapturing, setCaptureProgress, setScreenshots: recState.setScreenshots, setRecordStatus: recState.setRecordStatus })

  useEffect(() => {
    if (!canWrite || !id || !videoReady || recState.recordStatus !== 'screenshots_ready') return
    if (!recState.screenshots.length || recState.screenshots.some((s) => s.gcs_uri || s.localUrl) || captureStartedRef.current) return
    captureStartedRef.current = true
    const moments = recState.screenshots.map((s) => {
      const [start, end] = (s.timestamp || '').split('-')
      return { timestamp_start: start || '0:00', timestamp_end: end || start || '0:00' }
    })
    void captureScreenshots(recState.recordId || id, moments)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canWrite, id, videoReady, recState.recordStatus, recState.screenshots])

  return { capturing, captureProgress, setVideoReady, videoRef, canvasRef, captureScreenshots }
}

function buildThumbnailSourceHandlers(
  select: (url: string | null, gcs: string | null, name: string) => void,
  recState: ReturnType<typeof useThumbnailRecordState>,
) {
  const resetOutputs = () => {
    recState.setScreenshots([])
    recState.setThumbnailUrl(null)
    recState.setError(null)
  }
  return {
    handleSelectProduction: (prod: CompletedProductionSource) => {
      select(prod.video_signed_url, prod.final_video_url, prod.name)
      recState.setVideoSource('production')
      recState.setProductionId(prod.id)
      resetOutputs()
    },
    handleSelectUpload: (record: UploadRecord) => {
      select(record.signed_url || null, record.gcs_uri, record.display_name || record.filename)
      recState.setVideoSource('upload')
      recState.setProductionId(undefined)
      resetOutputs()
    },
    handleChangeVideo: () => {
      select(null, null, '')
      recState.setVideoSource('upload')
      recState.setProductionId(undefined)
      resetOutputs()
      recState.setRecordId(null)
      recState.setVideoSummary(null)
      recState.setRecordStatus('analyzing')
    },
  }
}

function useThumbnailActions(params: {
  gcsUri: string | null
  videoFilename: string
  analysisPromptId: string
  collagePromptId: string
  modelConfig: { modelId?: string; region?: string }
  recState: ReturnType<typeof useThumbnailRecordState>
  captureScreenshots: (rid: string, moments: { timestamp_start: string; timestamp_end: string }[]) => Promise<void>
  navigate: ReturnType<typeof useNavigate>
}) {
  const [analyzing, setAnalyzing] = useState(false)
  const [generatingCollage, setGeneratingCollage] = useState(false)
  const { recState } = params

  const handleAnalyze = async () => {
    if (!params.gcsUri || !params.analysisPromptId) return
    setAnalyzing(true)
    recState.setError(null)
    recState.setScreenshots([])
    recState.setThumbnailUrl(null)
    try {
      const result = await api.thumbnails.analyze({
        gcs_uri: params.gcsUri,
        prompt_id: params.analysisPromptId,
        video_filename: params.videoFilename,
        video_source: recState.videoSource,
        production_id: recState.productionId,
        model_id: params.modelConfig.modelId,
        region: params.modelConfig.region,
      })
      const moments = (result.data?.key_moments || []) as AnalyzeMomentInput[]
      recState.setVideoSummary(result.data?.video_summary || null)
      recState.setRecordId(result.id)
      recState.setRecordStatus('screenshots_ready')
      recState.setScreenshots(mapMomentsToScreenshots(moments))
      await params.captureScreenshots(result.id, moments)
      if (result.id) {
        recState.justCreatedRef.current = true
        params.navigate(`/thumbnails/${result.id}`, { replace: true })
      }
    } catch (e: unknown) {
      recState.setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleGenerateCollage = async () => {
    if (!recState.recordId || !params.collagePromptId) return
    setGeneratingCollage(true)
    recState.setError(null)
    recState.setRecordStatus('generating')
    try {
      const result = await api.thumbnails.generateCollage(recState.recordId, params.collagePromptId)
      if (result.thumbnail_signed_url) {
        recState.setThumbnailUrl(result.thumbnail_signed_url)
        recState.setRecordStatus('completed')
      }
    } catch (e: unknown) {
      recState.setError(e instanceof Error ? e.message : 'Collage generation failed')
      recState.setRecordStatus('screenshots_ready')
    } finally {
      setGeneratingCollage(false)
    }
  }

  return { analyzing, generatingCollage, handleAnalyze, handleGenerateCollage }
}

const ThumbnailVideoPlayerBox = ({
  videoUrl,
  showChangeButton,
  onChangeVideo,
  videoRef,
  onVideoReady,
}: {
  videoUrl: string
  showChangeButton: boolean
  onChangeVideo: () => void
  videoRef: React.RefObject<HTMLVideoElement>
  onVideoReady: () => void
}) => (
  <div className="space-y-2">
    {showChangeButton && (
      <Button variant="link" size="xs" onClick={onChangeVideo} className="px-0 h-auto text-xs text-accent-dark">
        Change Video
      </Button>
    )}
    <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
      <video
        ref={videoRef}
        controls
        crossOrigin="anonymous"
        onLoadedData={onVideoReady}
        className="w-full h-full"
        src={videoUrl}
      />
    </div>
  </div>
)

function useThumbnailsPageController(id: string | undefined) {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const isViewMode = !!id
  const sourceState = useVideoSourceState<UploadRecord, CompletedProductionSource>(
    {
      loadUploads: () => api.uploads.list({ file_type: 'video' }),
      loadProductions: () => api.thumbnails.listProductionSources(),
    },
    { initialTab: 'productions', enabled: !isViewMode },
  )
  const prompts = useThumbnailPrompts()
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const recState = useThumbnailRecordState(id, sourceState.select)
  const cap = useThumbnailCaptureState(id, canWrite, recState)
  const handlers = buildThumbnailSourceHandlers(sourceState.select, recState)
  const actions = useThumbnailActions({
    gcsUri: sourceState.gcsUri,
    videoFilename: sourceState.videoFilename,
    analysisPromptId: prompts.analysisPromptId,
    collagePromptId: prompts.collagePromptId,
    modelConfig,
    recState,
    captureScreenshots: cap.captureScreenshots,
    navigate,
  })
  return { navigate, canWrite, isViewMode, sourceState, prompts, modelConfig, setModelConfig, recState, cap, handlers, actions }
}

const ThumbnailsWorkBody = ({ id, ctrl }: { id?: string; ctrl: ReturnType<typeof useThumbnailsPageController> }) => {
  const { isViewMode, sourceState, prompts, modelConfig, setModelConfig, recState, cap, handlers, actions, navigate } = ctrl
  const hasScreenshots = recState.screenshots.length > 0
  const screenshotsCaptured = recState.screenshots.some((s) => s.gcs_uri || s.localUrl)
  const showCollageSection = ['screenshots_ready', 'generating', 'completed'].includes(recState.recordStatus) && screenshotsCaptured

  return (
    <>
      {!isViewMode && !sourceState.videoUrl && (
        <ThumbnailsSourcePicker sourceTab={sourceState.sourceTab} setSourceTab={sourceState.setSourceTab} productions={sourceState.productions} uploads={sourceState.uploads} loading={sourceState.loading} onSelectProduction={handlers.handleSelectProduction} onSelectUpload={handlers.handleSelectUpload} onNavigateUploads={() => navigate('/uploads')} />
      )}
      {sourceState.videoUrl && (
        <ThumbnailVideoPlayerBox videoUrl={sourceState.videoUrl} showChangeButton={!isViewMode && !hasScreenshots} onChangeVideo={handlers.handleChangeVideo} videoRef={cap.videoRef} onVideoReady={() => cap.setVideoReady(true)} />
      )}
      {sourceState.videoUrl && !hasScreenshots && !isViewMode && (
        <ThumbnailAnalyzeControls analysisPrompts={prompts.analysisPrompts} analysisPromptId={prompts.analysisPromptId} setAnalysisPromptId={prompts.setAnalysisPromptId} modelConfig={modelConfig} setModelConfig={setModelConfig} analyzing={actions.analyzing} onAnalyze={actions.handleAnalyze} />
      )}
      <ThumbnailOutputSections id={id} error={recState.error} videoSummary={recState.videoSummary} screenshots={recState.screenshots} capturing={cap.capturing} captureProgress={cap.captureProgress} showCollageSection={showCollageSection} thumbnailUrl={recState.thumbnailUrl} showResultSection={recState.recordStatus === 'completed' && !!recState.thumbnailUrl} collagePrompts={prompts.collagePrompts} collagePromptId={prompts.collagePromptId} setCollagePromptId={prompts.setCollagePromptId} generatingCollage={actions.generatingCollage} onGenerateCollage={actions.handleGenerateCollage} />
    </>
  )
}

export const ThumbnailsWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const ctrl = useThumbnailsPageController(id)

  if (ctrl.recState.loadingRecord) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading thumbnail record...</p>
      </div>
    )
  }

  return (
    <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="max-w-5xl mx-auto space-y-6 pb-20">
      <canvas ref={ctrl.cap.canvasRef} className="hidden" />
      <ThumbnailsPageHeader
        id={id}
        isViewMode={ctrl.isViewMode}
        canWrite={ctrl.canWrite}
        videoFilename={ctrl.sourceState.videoFilename}
        setVideoFilename={ctrl.sourceState.setVideoFilename}
        modelName={ctrl.recState.modelName}
        showAddFiles={!ctrl.isViewMode && !ctrl.sourceState.videoUrl}
        onNavigateUploads={() => ctrl.navigate('/uploads')}
      />
      <ThumbnailsWorkBody id={id} ctrl={ctrl} />
    </motion.div>
  )
}
