import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { motion } from 'framer-motion'
import { Zap, Loader2, ArrowLeft, Upload, Pencil, Check } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { ModelPill } from '@/components/ModelPill'
import { Select } from '@/components/UI'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { cn, parseTimestamp } from '@/lib/utils'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { KeyMomentsSourcePicker } from '@/components/pages/keyMoments/KeyMomentsSourcePicker'
import { KeyMomentsTimeline } from '@/components/pages/keyMoments/KeyMomentsTimeline'
import type { KeyMomentsAnalysis, SystemResource, KeyMomentsRecord, CompletedProductionSource, UploadRecord } from '@/types/project'

export const KeyMomentsAnalyzePage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isMaster } = useAuthStore()
  const isViewMode = !!id

  const {
    sourceTab, setSourceTab,
    videoUrl, gcsUri, videoFilename, setVideoFilename,
    productions, uploads, loading: loadingSources,
    select,
  } = useVideoSourceState<UploadRecord, CompletedProductionSource>(
    {
      loadUploads: () => api.uploads.list({ file_type: 'video' }),
      loadProductions: () => api.keyMoments.listProductionSources(),
    },
    { initialTab: 'productions', enabled: !isViewMode },
  )
  const [videoSource, setVideoSource] = useState<'upload' | 'production'>('upload')
  const [productionId, setProductionId] = useState<string | undefined>()

  // Name editing
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  // Prompt state
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')

  // Model/region config
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})

  // Analysis state
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<KeyMomentsAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Model name (from record usage)
  const [modelName, setModelName] = useState<string | undefined>()

  // View mode loading
  const [loadingRecord, setLoadingRecord] = useState(false)

  // Player state
  const videoRef = useRef<HTMLVideoElement>(null)
  const videoContainerRef = useRef<HTMLDivElement>(null)
  const [activeMomentIndex, setActiveMomentIndex] = useState<number | null>(null)

  // Fetch prompts on mount
  useEffect(() => {
    api.system.listResources('prompt', 'key-moments').then(setPrompts).catch(console.error)
  }, [])

  // If view mode, fetch the record
  useEffect(() => {
    if (!id) return
    setLoadingRecord(true)
    api.keyMoments.get(id)
      .then((record: KeyMomentsRecord) => {
        select(
          record.video_signed_url || null,
          record.video_gcs_uri,
          record.display_name || record.video_filename,
        )
        setVideoSource(record.video_source)
        setProductionId(record.production_id)
        setModelName(record.usage?.model_name)
        setAnalysis({
          key_moments: record.key_moments,
          video_summary: record.video_summary,
        })
      })
      .catch((err) => setError(err.message || 'Failed to load analysis'))
      .finally(() => setLoadingRecord(false))
  }, [id])

  // Auto-pause at moment end
  const handleTimeUpdate = useCallback(() => {
    if (activeMomentIndex === null || !analysis) return
    const moment = analysis.key_moments[activeMomentIndex]
    if (!moment || !videoRef.current) return
    const endSec = parseTimestamp(moment.timestamp_end)
    if (videoRef.current.currentTime >= endSec) {
      videoRef.current.pause()
      setActiveMomentIndex(null)
    }
  }, [activeMomentIndex, analysis])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.addEventListener('timeupdate', handleTimeUpdate)
    return () => video.removeEventListener('timeupdate', handleTimeUpdate)
  }, [handleTimeUpdate])

  const handleSelectProduction = (prod: CompletedProductionSource) => {
    select(prod.video_signed_url, prod.final_video_url, prod.name)
    setVideoSource('production')
    setProductionId(prod.id)
    setAnalysis(null)
    setError(null)
  }

  const handleSelectUpload = (record: UploadRecord) => {
    select(record.signed_url || null, record.gcs_uri, record.display_name || record.filename)
    setVideoSource('upload')
    setProductionId(undefined)
    setAnalysis(null)
    setError(null)
  }

  const handleChangeVideo = () => {
    select(null, null, '')
    setVideoSource('upload')
    setProductionId(undefined)
    setAnalysis(null)
    setError(null)
  }

  const handleAnalyze = async () => {
    if (!gcsUri || !promptId) return
    setAnalyzing(true)
    setError(null)
    try {
      const result = await api.keyMoments.analyze({
        gcs_uri: gcsUri,
        prompt_id: promptId,
        video_filename: videoFilename,
        video_source: videoSource,
        production_id: productionId,
        model_id: modelConfig.modelId,
        region: modelConfig.region,
      })
      setAnalysis(result.data)
      if (result.id) {
        navigate(`/key-moments/${result.id}`, { replace: true })
      }
    } catch (e: any) {
      setError(e.message || 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  const seekToMoment = (index: number) => {
    if (!videoRef.current || !analysis) return
    const moment = analysis.key_moments[index]
    videoRef.current.currentTime = parseTimestamp(moment.timestamp_start)
    videoRef.current.play()
    setActiveMomentIndex(index)
    videoContainerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  if (loadingRecord) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading analysis...</p>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="max-w-5xl mx-auto space-y-6 pb-20"
    >
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          to="/key-moments"
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft size={14} />
          Back to Key Moments
        </Link>
      </div>

      <div className="flex items-center justify-between">
        <div>
          {isViewMode ? (
            <>
              {isEditingName ? (
                <form className="flex items-center gap-2" onSubmit={async (e) => {
                  e.preventDefault()
                  if (id) await api.keyMoments.update(id, { display_name: editName })
                  setVideoFilename(editName)
                  setIsEditingName(false)
                }}>
                  <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                    className="text-2xl font-heading font-bold text-foreground bg-muted px-2 py-0.5 rounded border border-border focus:outline-none focus:ring-1 focus:ring-accent" />
                  <button type="submit" className="text-accent hover:text-accent-dark"><Check size={16} /></button>
                </form>
              ) : isMaster ? (
                <button className="flex items-center gap-2 text-2xl font-heading text-foreground tracking-tight hover:text-accent-dark transition-colors"
                  onClick={() => { setEditName(videoFilename || ''); setIsEditingName(true) }}>
                  {videoFilename || 'Untitled'}
                  <Pencil size={12} className="text-muted-foreground" />
                </button>
              ) : (
                <h2 className="text-2xl font-heading text-foreground tracking-tight">{videoFilename || 'Untitled'}</h2>
              )}
              <div className="flex items-center gap-2 mt-1">
                <p className="text-sm text-muted-foreground">Key Moments Analysis</p>
                <ModelPill modelName={modelName} />
              </div>
            </>
          ) : (
            <>
              <h2 className="text-2xl font-heading text-foreground tracking-tight">Find Key Moments</h2>
              <p className="text-sm text-muted-foreground mt-1">Select a video source and let AI identify the key moments.</p>
            </>
          )}
        </div>
        {!isViewMode && !videoUrl && (
          <button
            onClick={() => navigate('/uploads')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-muted hover:bg-accent/10 text-xs font-medium text-muted-foreground hover:text-foreground transition-all"
          >
            <Upload size={14} />
            Add Files
          </button>
        )}
      </div>

      {!isViewMode && !videoUrl && (
        <KeyMomentsSourcePicker
          sourceTab={sourceTab}
          setSourceTab={setSourceTab}
          productions={productions}
          uploads={uploads}
          loading={loadingSources}
          onSelectProduction={handleSelectProduction}
          onSelectUpload={handleSelectUpload}
          onNavigateUploads={() => navigate('/uploads')}
        />
      )}

      {/* Video Player */}
      {videoUrl && (
        <div className="space-y-2">
          {!isViewMode && (
            <button
              onClick={handleChangeVideo}
              className="text-xs text-accent-dark hover:underline cursor-pointer"
            >
              Change Video
            </button>
          )}
          <div ref={videoContainerRef} className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
            <video
              ref={videoRef}
              controls
              className="w-full h-full"
              src={videoUrl}
            />
          </div>
        </div>
      )}

      {/* Analyze controls */}
      {videoUrl && !analysis && !isViewMode && (
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <Select
              label="Prompt"
              value={promptId}
              onChange={setPromptId}
              options={prompts.map(p => ({
                value: p.id,
                label: p.name,
                description: `Version ${p.version}`
              }))}
              placeholder="Select a prompt..."
            />
            {prompts.length === 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                No key-moments prompts found. Create one in System Prompts with category "key-moments".
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} className="mt-2" />
            <Button
              icon={analyzing ? Loader2 : Zap}
              onClick={handleAnalyze}
              disabled={analyzing || !promptId}
              className={cn(analyzing && "[&_svg]:animate-spin")}
            >
              {analyzing ? 'Analyzing...' : 'Analyze Video'}
            </Button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
          {error}
        </div>
      )}

      {/* Video Summary */}
      {analysis?.video_summary && (
        <Card id="video-summary" title="Video Summary">
          <p className="text-sm leading-relaxed">{analysis.video_summary}</p>
        </Card>
      )}

      {analysis && analysis.key_moments.length > 0 && (
        <KeyMomentsTimeline
          moments={analysis.key_moments}
          activeMomentIndex={activeMomentIndex}
          onSeek={seekToMoment}
        />
      )}
      {id && <div className="mt-6"><ServicesUsedPanel feature="key_moments" recordId={id} /></div>}
    </motion.div>
  )
}
