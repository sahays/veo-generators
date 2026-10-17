import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { motion } from 'framer-motion'
import { Zap, Loader2, ArrowLeft, Upload, Pencil, Check } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { ModelPill } from '@/components/ModelPill'
import { Select } from '@/components/UI'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/hooks/useApiClient'
import { useAuthStore } from '@/store/useAuthStore'
import { cn, parseTimestamp } from '@/lib/utils'
import { captureVideoFrames } from '@/lib/captureFrames'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { KeyMomentsSourcePicker } from '@/components/pages/keyMoments/components/KeyMomentsSourcePicker'
import { KeyMomentsTimeline } from '@/components/pages/keyMoments/components/KeyMomentsTimeline'
import type {
  KeyMomentsAnalysis,
  SystemResource,
  KeyMomentsRecord,
  CompletedProductionSource,
  UploadRecord,
} from '@/types/project'

async function captureAndSaveKeyFrames(
  video: HTMLVideoElement | null,
  canvas: HTMLCanvasElement | null,
  rid: string,
  moments: KeyMomentsAnalysis['key_moments'],
  setAnalysis: React.Dispatch<React.SetStateAction<KeyMomentsAnalysis | null>>,
  setCapturing: (v: boolean) => void,
) {
  if (!video || !canvas) return
  setCapturing(true)
  const captured = await captureVideoFrames(video, canvas, moments, (frame) => {
    setAnalysis((prev) => {
      if (!prev) return prev
      const km = [...prev.key_moments]
      if (km[frame.index]) km[frame.index] = { ...km[frame.index], frame_gcs_uri: frame.gcs_uri, frame_signed_url: frame.signed_url }
      return { ...prev, key_moments: km }
    })
  })
  if (captured.length > 0) {
    await api.keyMoments.saveFrames(rid, captured.map((c) => ({ index: c.index, gcs_uri: c.gcs_uri })))
  }
  setCapturing(false)
}

function useKeyMomentsRecordLoader(id: string | undefined, select: (url: string | null, gcs: string | null, name: string) => void) {
  const [videoSource, setVideoSource] = useState<'upload' | 'production'>('upload')
  const [productionId, setProductionId] = useState<string | undefined>()
  const [modelName, setModelName] = useState<string | undefined>()
  const [analysis, setAnalysis] = useState<KeyMomentsAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadingRecord, setLoadingRecord] = useState(false)

  useEffect(() => {
    if (!id) return
    setLoadingRecord(true)
    api.keyMoments
      .get(id)
      .then((record: KeyMomentsRecord) => {
        select(record.video_signed_url || null, record.video_gcs_uri, record.display_name || record.video_filename)
        setVideoSource(record.video_source)
        setProductionId(record.production_id)
        setModelName(record.usage?.model_name)
        setAnalysis({ key_moments: record.key_moments, video_summary: record.video_summary })
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load analysis'))
      .finally(() => setLoadingRecord(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  return { videoSource, setVideoSource, productionId, setProductionId, modelName, analysis, setAnalysis, error, setError, loadingRecord }
}

function useMomentPauseOnEnd(videoRef: React.RefObject<HTMLVideoElement>, activeMomentIndex: number | null, setActiveMomentIndex: (i: number | null) => void, analysis: KeyMomentsAnalysis | null) {
  const handleTimeUpdate = useCallback(() => {
    if (activeMomentIndex === null || !analysis) return
    const moment = analysis.key_moments[activeMomentIndex]
    if (moment && videoRef.current && videoRef.current.currentTime >= parseTimestamp(moment.timestamp_end)) {
      videoRef.current.pause()
      setActiveMomentIndex(null)
    }
  }, [activeMomentIndex, analysis, setActiveMomentIndex, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.addEventListener('timeupdate', handleTimeUpdate)
    return () => video.removeEventListener('timeupdate', handleTimeUpdate)
  }, [handleTimeUpdate, videoRef])
}

function useVideoPlayerCapture(
  id: string | undefined,
  canWrite: boolean,
  videoUrl: string | null,
  analysis: KeyMomentsAnalysis | null,
  setAnalysis: React.Dispatch<React.SetStateAction<KeyMomentsAnalysis | null>>,
) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const videoContainerRef = useRef<HTMLDivElement>(null)
  const [activeMomentIndex, setActiveMomentIndex] = useState<number | null>(null)
  const [videoReady, setVideoReady] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const captureStartedRef = useRef(false)

  useEffect(() => { setVideoReady(false); captureStartedRef.current = false }, [videoUrl])
  useMomentPauseOnEnd(videoRef, activeMomentIndex, setActiveMomentIndex, analysis)

  useEffect(() => {
    if (!canWrite || !id || !videoReady || !analysis) return
    const moments = analysis.key_moments
    if (!moments?.length || moments.every((m) => m.frame_signed_url) || captureStartedRef.current) return
    captureStartedRef.current = true
    captureAndSaveKeyFrames(videoRef.current, canvasRef.current, id, moments, setAnalysis, setCapturing)
  }, [canWrite, id, videoReady, analysis, setAnalysis])

  const seekToMoment = (index: number) => {
    if (!videoRef.current || !analysis) return
    videoRef.current.currentTime = parseTimestamp(analysis.key_moments[index].timestamp_start)
    videoRef.current.play()
    setActiveMomentIndex(index)
    videoContainerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
  return { videoRef, canvasRef, videoContainerRef, activeMomentIndex, setVideoReady, capturing, seekToMoment }
}

const KeyMomentsHeader = ({
  id,
  isViewMode,
  canWrite,
  videoFilename,
  setVideoFilename,
  modelName,
  showAddFiles,
  onNavigateUploads,
}: {
  id?: string
  isViewMode: boolean
  canWrite: boolean
  videoFilename: string
  setVideoFilename: (name: string) => void
  modelName?: string
  showAddFiles: boolean
  onNavigateUploads: () => void
}) => {
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')
  const handleRename = async (e: React.FormEvent) => {
    e.preventDefault()
    if (id) await api.keyMoments.update(id, { display_name: editName })
    setVideoFilename(editName)
    setIsEditingName(false)
  }
  return (
    <div className="flex items-center justify-between">
      <div>
        {isViewMode ? (
          <>
            {isEditingName ? (
              <form className="flex items-center gap-2" onSubmit={handleRename}>
                <Input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} className="h-9 text-2xl font-heading font-bold text-foreground bg-muted px-2 py-0.5" />
                <Button type="submit" variant="ghost" size="icon" className="h-7 w-7 text-accent hover:text-accent-dark"><Check size={16} /></Button>
              </form>
            ) : canWrite ? (
              <Button variant="unstyled" className="flex items-center gap-2 text-2xl font-heading text-foreground tracking-tight hover:text-accent-dark transition-colors" onClick={() => { setEditName(videoFilename || ''); setIsEditingName(true) }}>
                {videoFilename || 'Untitled'}<Pencil size={12} className="text-muted-foreground" />
              </Button>
            ) : (
              <h2 className="text-2xl font-heading text-foreground tracking-tight">{videoFilename || 'Untitled'}</h2>
            )}
            <div className="flex items-center gap-2 mt-1"><p className="text-sm text-muted-foreground">Key Moments Analysis</p><ModelPill modelName={modelName} /></div>
          </>
        ) : (
          <><h2 className="text-2xl font-heading text-foreground tracking-tight">Find Key Moments</h2><p className="text-sm text-muted-foreground mt-1">Select a video source and let AI identify the key moments.</p></>
        )}
      </div>
      {showAddFiles && <Button variant="secondary" size="sm" icon={Upload} onClick={onNavigateUploads}>Add Files</Button>}
    </div>
  )
}

const AnalyzeControlsBar = ({
  prompts,
  promptId,
  setPromptId,
  modelConfig,
  setModelConfig,
  analyzing,
  onAnalyze,
}: {
  prompts: SystemResource[]
  promptId: string
  setPromptId: (v: string) => void
  modelConfig: { modelId?: string; region?: string }
  setModelConfig: (v: { modelId?: string; region?: string }) => void
  analyzing: boolean
  onAnalyze: () => void
}) => (
  <div className="space-y-1.5">
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex-1 min-w-[220px]">
        <Select label="Prompt" value={promptId} onChange={setPromptId} options={prompts.map((p) => ({ value: p.id, label: p.name, description: `Version ${p.version}` }))} placeholder="Select a prompt..." />
      </div>
      <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />
      <Button icon={analyzing ? Loader2 : Zap} onClick={onAnalyze} disabled={analyzing || !promptId} className={cn('py-2.5 shrink-0', analyzing && '[&_svg]:animate-spin')}>
        {analyzing ? 'Analyzing...' : 'Analyze Video'}
      </Button>
    </div>
    {prompts.length === 0 && <p className="text-xs text-muted-foreground">No key-moments prompts found. Create one in System Prompts with category &quot;key-moments&quot;.</p>}
  </div>
)

function useKeyMomentsPromptsAndRun(params: {
  gcsUri: string | null
  videoFilename: string
  videoSource: 'upload' | 'production'
  productionId?: string
  setAnalysis: React.Dispatch<React.SetStateAction<KeyMomentsAnalysis | null>>
  setError: (v: string | null) => void
  navigate: ReturnType<typeof useNavigate>
}) {
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [analyzing, setAnalyzing] = useState(false)

  useEffect(() => {
    api.system.listResources('prompt', 'key-moments').then(setPrompts).catch(() => {})
  }, [])

  const handleAnalyze = async () => {
    if (!params.gcsUri || !promptId) return
    setAnalyzing(true)
    params.setError(null)
    try {
      const result = await api.keyMoments.analyze({
        gcs_uri: params.gcsUri,
        prompt_id: promptId,
        video_filename: params.videoFilename,
        video_source: params.videoSource,
        production_id: params.productionId,
        model_id: modelConfig.modelId,
        region: modelConfig.region,
      })
      params.setAnalysis(result.data)
      if (result.id) params.navigate(`/key-moments/${result.id}`, { replace: true })
    } catch (e: unknown) {
      params.setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }
  return { prompts, promptId, setPromptId, modelConfig, setModelConfig, analyzing, handleAnalyze }
}

const KeyMomentsVideoPlayerSection = ({
  videoUrl,
  isViewMode,
  onChangeVideo,
  videoContainerRef,
  videoRef,
  canvasRef,
  onVideoReady,
}: {
  videoUrl: string
  isViewMode: boolean
  onChangeVideo: () => void
  videoContainerRef: React.RefObject<HTMLDivElement>
  videoRef: React.RefObject<HTMLVideoElement>
  canvasRef: React.RefObject<HTMLCanvasElement>
  onVideoReady: () => void
}) => (
  <div className="space-y-2">
    {!isViewMode && <Button variant="link" size="xs" onClick={onChangeVideo} className="px-0 h-auto text-xs text-accent-dark">Change Video</Button>}
    <div ref={videoContainerRef} className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
      <video ref={videoRef} controls crossOrigin="anonymous" onLoadedData={onVideoReady} className="w-full h-full" src={videoUrl} />
    </div>
    <canvas ref={canvasRef} className="hidden" />
  </div>
)

function buildSourceHandlers(select: (url: string | null, gcs: string | null, name: string) => void, loader: ReturnType<typeof useKeyMomentsRecordLoader>) {
  const clearResult = () => { loader.setAnalysis(null); loader.setError(null) }
  return {
    onSelectProduction: (prod: CompletedProductionSource) => {
      select(prod.video_signed_url, prod.final_video_url, prod.name)
      loader.setVideoSource('production')
      loader.setProductionId(prod.id)
      clearResult()
    },
    onSelectUpload: (record: UploadRecord) => {
      select(record.signed_url || null, record.gcs_uri, record.display_name || record.filename)
      loader.setVideoSource('upload')
      loader.setProductionId(undefined)
      clearResult()
    },
    onChangeVideo: () => {
      select(null, null, '')
      loader.setVideoSource('upload')
      loader.setProductionId(undefined)
      clearResult()
    },
  }
}

const KeyMomentsBodySection = ({
  id,
  isViewMode,
  videoUrl,
  sourceState,
  handlers,
  player,
  runner,
  loader,
  onNavigateUploads,
}: {
  id?: string
  isViewMode: boolean
  videoUrl: string | null
  sourceState: ReturnType<typeof useVideoSourceState<UploadRecord, CompletedProductionSource>>
  handlers: ReturnType<typeof buildSourceHandlers>
  player: ReturnType<typeof useVideoPlayerCapture>
  runner: ReturnType<typeof useKeyMomentsPromptsAndRun>
  loader: ReturnType<typeof useKeyMomentsRecordLoader>
  onNavigateUploads: () => void
}) => (
  <>
    {!isViewMode && !videoUrl && (
      <KeyMomentsSourcePicker sourceTab={sourceState.sourceTab} setSourceTab={sourceState.setSourceTab} productions={sourceState.productions} uploads={sourceState.uploads} loading={sourceState.loading} onSelectProduction={handlers.onSelectProduction} onSelectUpload={handlers.onSelectUpload} onNavigateUploads={onNavigateUploads} />
    )}
    {videoUrl && (
      <KeyMomentsVideoPlayerSection videoUrl={videoUrl} isViewMode={isViewMode} onChangeVideo={handlers.onChangeVideo} videoContainerRef={player.videoContainerRef} videoRef={player.videoRef} canvasRef={player.canvasRef} onVideoReady={() => player.setVideoReady(true)} />
    )}
    {videoUrl && !loader.analysis && !isViewMode && (
      <AnalyzeControlsBar prompts={runner.prompts} promptId={runner.promptId} setPromptId={runner.setPromptId} modelConfig={runner.modelConfig} setModelConfig={runner.setModelConfig} analyzing={runner.analyzing} onAnalyze={runner.handleAnalyze} />
    )}
    {loader.error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">{loader.error}</div>}
    {loader.analysis?.video_summary && <Card id="video-summary" title="Video Summary"><p className="text-sm leading-relaxed">{loader.analysis.video_summary}</p></Card>}
    {loader.analysis && loader.analysis.key_moments.length > 0 && (
      <KeyMomentsTimeline moments={loader.analysis.key_moments} activeMomentIndex={player.activeMomentIndex} onSeek={player.seekToMoment} capturing={player.capturing} />
    )}
    {id && <div className="mt-6"><ServicesUsedPanel feature="key_moments" recordId={id} /></div>}
  </>
)

export const KeyMomentsAnalyzePage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const isViewMode = !!id

  const sourceState = useVideoSourceState<UploadRecord, CompletedProductionSource>(
    { loadUploads: () => api.uploads.list({ file_type: 'video' }), loadProductions: () => api.keyMoments.listProductionSources() },
    { initialTab: 'productions', enabled: !isViewMode },
  )
  const loader = useKeyMomentsRecordLoader(id, sourceState.select)
  const player = useVideoPlayerCapture(id, canWrite, sourceState.videoUrl, loader.analysis, loader.setAnalysis)
  const runner = useKeyMomentsPromptsAndRun({
    gcsUri: sourceState.gcsUri, videoFilename: sourceState.videoFilename, videoSource: loader.videoSource,
    productionId: loader.productionId, setAnalysis: loader.setAnalysis, setError: loader.setError, navigate,
  })
  const handlers = buildSourceHandlers(sourceState.select, loader)

  if (loader.loadingRecord) {
    return <div className="flex flex-col items-center justify-center py-32 space-y-4"><Loader2 className="animate-spin text-accent" size={32} /><p className="text-sm text-muted-foreground">Loading analysis...</p></div>
  }
  return (
    <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="max-w-5xl mx-auto space-y-6 pb-20">
      <div className="flex items-center gap-3"><Link to="/key-moments" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"><ArrowLeft size={14} /> Back to Key Moments</Link></div>
      <KeyMomentsHeader id={id} isViewMode={isViewMode} canWrite={canWrite} videoFilename={sourceState.videoFilename} setVideoFilename={sourceState.setVideoFilename} modelName={loader.modelName} showAddFiles={!isViewMode && !sourceState.videoUrl} onNavigateUploads={() => navigate('/uploads')} />
      <KeyMomentsBodySection id={id} isViewMode={isViewMode} videoUrl={sourceState.videoUrl} sourceState={sourceState} handlers={handlers} player={player} runner={runner} loader={loader} onNavigateUploads={() => navigate('/uploads')} />
    </motion.div>
  )
}

