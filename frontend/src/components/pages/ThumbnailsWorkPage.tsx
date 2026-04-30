import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { motion } from 'framer-motion'
import {
  Upload, Loader2, ArrowLeft, Camera, Sparkles, Pencil, Check,
} from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { ModelPill } from '@/components/ModelPill'
import { Select } from '@/components/UI'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/lib/api'
import { useAuthStore } from '@/store/useAuthStore'
import { cn, parseTimestamp } from '@/lib/utils'
import { useVideoSourceState } from '@/hooks/useVideoSourceState'
import { ThumbnailsResult } from '@/components/pages/thumbnails/ThumbnailsResult'
import { ThumbnailsScreenshotGrid } from '@/components/pages/thumbnails/ThumbnailsScreenshotGrid'
import { ThumbnailsSourcePicker } from '@/components/pages/thumbnails/ThumbnailsSourcePicker'
import type { ThumbnailRecord, ThumbnailScreenshot, SystemResource, CompletedProductionSource, UploadRecord } from '@/types/project'

export const ThumbnailsWorkPage = () => {
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
      loadProductions: () => api.thumbnails.listProductionSources(),
    },
    { initialTab: 'productions', enabled: !isViewMode },
  )
  const [videoSource, setVideoSource] = useState<'upload' | 'production'>('upload')
  const [productionId, setProductionId] = useState<string | undefined>()

  // Name editing
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  // Analysis prompt state
  const [analysisPrompts, setAnalysisPrompts] = useState<SystemResource[]>([])
  const [analysisPromptId, setAnalysisPromptId] = useState('')

  // Collage prompt state
  const [collagePrompts, setCollagePrompts] = useState<SystemResource[]>([])
  const [collagePromptId, setCollagePromptId] = useState('')

  // Model/region config
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})

  // Analysis state
  const [analyzing, setAnalyzing] = useState(false)
  const [screenshots, setScreenshots] = useState<(ThumbnailScreenshot & { localUrl?: string })[]>([])
  const [videoSummary, setVideoSummary] = useState<string | null>(null)
  const [recordId, setRecordId] = useState<string | null>(id || null)
  const [error, setError] = useState<string | null>(null)

  // Screenshot capture state
  const [capturing, setCapturing] = useState(false)
  const [captureProgress, setCaptureProgress] = useState(0)

  // Collage state
  const [generatingCollage, setGeneratingCollage] = useState(false)
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null)
  const [recordStatus, setRecordStatus] = useState<string>('analyzing')

  // Model name (from record usage)
  const [modelName, setModelName] = useState<string | undefined>()

  // View mode loading
  const [loadingRecord, setLoadingRecord] = useState(false)

  // Ref to skip view-mode fetch after create flow navigates
  const justCreatedRef = useRef(false)

  // Video ref
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Fetch prompts on mount
  useEffect(() => {
    api.system.listResources('prompt', 'thumbnails').then(setAnalysisPrompts).catch(console.error)
    api.system.listResources('prompt', 'collage').then(setCollagePrompts).catch(console.error)
  }, [])

  // If view mode, fetch the record (skip if we just created it)
  useEffect(() => {
    if (!id) return
    if (justCreatedRef.current) {
      justCreatedRef.current = false
      return
    }
    setLoadingRecord(true)
    api.thumbnails.get(id)
      .then((record: ThumbnailRecord) => {
        select(
          record.video_signed_url || null,
          record.video_gcs_uri,
          record.display_name || record.video_filename,
        )
        setVideoSource(record.video_source)
        setProductionId(record.production_id)
        setVideoSummary(record.video_summary || null)
        setModelName((record as any).usage?.model_name)
        setScreenshots(record.screenshots.map(s => ({
          ...s,
          localUrl: s.signed_url,
        })))
        setRecordId(record.id)
        setRecordStatus(record.status)
        if (record.thumbnail_signed_url) {
          setThumbnailUrl(record.thumbnail_signed_url)
        }
      })
      .catch((err) => setError(err.message || 'Failed to load record'))
      .finally(() => setLoadingRecord(false))
  }, [id])

  const handleSelectProduction = (prod: CompletedProductionSource) => {
    select(prod.video_signed_url, prod.final_video_url, prod.name)
    setVideoSource('production')
    setProductionId(prod.id)
    setScreenshots([])
    setThumbnailUrl(null)
    setError(null)
  }

  const handleSelectUpload = (record: UploadRecord) => {
    select(record.signed_url || null, record.gcs_uri, record.display_name || record.filename)
    setVideoSource('upload')
    setProductionId(undefined)
    setScreenshots([])
    setThumbnailUrl(null)
    setError(null)
  }

  const handleChangeVideo = () => {
    select(null, null, '')
    setVideoSource('upload')
    setProductionId(undefined)
    setScreenshots([])
    setThumbnailUrl(null)
    setError(null)
    setRecordId(null)
    setVideoSummary(null)
    setRecordStatus('analyzing')
  }

  const captureScreenshots = async (rid: string, moments: { timestamp_start: string; timestamp_end: string }[]) => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !rid) return

    setCapturing(true)
    setCaptureProgress(0)
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const captured: { index: number; gcs_uri: string; signed_url: string }[] = []

    for (let i = 0; i < moments.length; i++) {
      const moment = moments[i]
      const startSec = parseTimestamp(moment.timestamp_start)
      const endSec = parseTimestamp(moment.timestamp_end)
      const midpoint = (startSec + endSec) / 2

      video.currentTime = midpoint
      await new Promise<void>(resolve => {
        video.addEventListener('seeked', () => resolve(), { once: true })
      })

      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      ctx.drawImage(video, 0, 0)

      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
      if (!blob) continue

      const file = new File([blob], `screenshot-${i}.png`, { type: 'image/png' })
      const result = await api.assets.upload(file)
      captured.push({ index: i, gcs_uri: result.gcs_uri, signed_url: result.signed_url })

      setScreenshots(prev => {
        const updated = [...prev]
        if (updated[i]) {
          updated[i] = { ...updated[i], gcs_uri: result.gcs_uri, localUrl: result.signed_url }
        }
        return updated
      })

      setCaptureProgress(i + 1)
    }

    if (captured.length > 0) {
      await api.thumbnails.saveScreenshots(
        rid,
        captured.map(c => ({ index: c.index, gcs_uri: c.gcs_uri }))
      )
      setRecordStatus('screenshots_ready')
    }

    setCapturing(false)
  }

  const handleAnalyze = async () => {
    if (!gcsUri || !analysisPromptId) return
    setAnalyzing(true)
    setError(null)
    setScreenshots([])
    setThumbnailUrl(null)
    try {
      const result = await api.thumbnails.analyze({
        gcs_uri: gcsUri,
        prompt_id: analysisPromptId,
        video_filename: videoFilename,
        video_source: videoSource,
        production_id: productionId,
        model_id: modelConfig.modelId,
        region: modelConfig.region,
      })

      const data = result.data
      const newRecordId = result.id
      setVideoSummary(data?.video_summary || null)
      setRecordId(newRecordId)
      setRecordStatus('screenshots_ready')

      const moments = data?.key_moments || []
      const newScreenshots: (ThumbnailScreenshot & { localUrl?: string })[] = moments.map((m: any) => ({
        timestamp: `${m.timestamp_start}-${m.timestamp_end}`,
        title: m.title || '',
        description: m.description || '',
        visual_characteristics: m.visual_characteristics || '',
        category: m.category,
        tags: m.tags || [],
        gcs_uri: '',
        localUrl: undefined,
      }))
      setScreenshots(newScreenshots)

      await captureScreenshots(newRecordId, moments)

      if (newRecordId) {
        justCreatedRef.current = true
        navigate(`/thumbnails/${newRecordId}`, { replace: true })
      }
    } catch (e: any) {
      setError(e.message || 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleGenerateCollage = async () => {
    if (!recordId || !collagePromptId) return
    setGeneratingCollage(true)
    setError(null)
    setRecordStatus('generating')
    try {
      const result = await api.thumbnails.generateCollage(recordId, collagePromptId)
      if (result.thumbnail_signed_url) {
        setThumbnailUrl(result.thumbnail_signed_url)
        setRecordStatus('completed')
      }
    } catch (e: any) {
      setError(e.message || 'Collage generation failed')
      setRecordStatus('screenshots_ready')
    } finally {
      setGeneratingCollage(false)
    }
  }

  if (loadingRecord) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading thumbnail record...</p>
      </div>
    )
  }

  const hasScreenshots = screenshots.length > 0
  const screenshotsCaptured = screenshots.some(s => s.gcs_uri || s.localUrl)
  const showCollageSection = (recordStatus === 'screenshots_ready' || recordStatus === 'generating' || recordStatus === 'completed') && screenshotsCaptured
  const showResultSection = recordStatus === 'completed' && thumbnailUrl

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="max-w-5xl mx-auto space-y-6 pb-20"
    >
      {/* Hidden canvas for screenshot capture */}
      <canvas ref={canvasRef} className="hidden" />

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          to="/thumbnails"
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft size={14} />
          Back to Thumbnails
        </Link>
      </div>

      <div className="flex items-center justify-between">
        <div>
          {isViewMode ? (
            <>
              {isEditingName ? (
                <form className="flex items-center gap-2" onSubmit={async (e) => {
                  e.preventDefault()
                  if (id) await api.thumbnails.update(id, { display_name: editName })
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
                <p className="text-sm text-muted-foreground">Thumbnail Details</p>
                <ModelPill modelName={modelName} />
              </div>
            </>
          ) : (
            <>
              <h2 className="text-2xl font-heading text-foreground tracking-tight">Create Thumbnail</h2>
              <p className="text-sm text-muted-foreground mt-1">Select a video, identify key moments, then generate a collage thumbnail.</p>
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
        <ThumbnailsSourcePicker
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

      {/* Section 1: Video Player + Analyze */}
      {videoUrl && (
        <div className="space-y-2">
          {!isViewMode && !hasScreenshots && (
            <button
              onClick={handleChangeVideo}
              className="text-xs text-accent-dark hover:underline cursor-pointer"
            >
              Change Video
            </button>
          )}
          <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
            <video
              ref={videoRef}
              controls
              crossOrigin="anonymous"
              className="w-full h-full"
              src={videoUrl}
            />
          </div>
        </div>
      )}

      {/* Analyze controls (fresh mode, video selected, no analysis yet) */}
      {videoUrl && !hasScreenshots && !isViewMode && (
        <div className="flex items-end gap-4">
          <div className="flex-1 min-w-0">
            <Select
              label="Thumbnail Analysis Prompt"
              value={analysisPromptId}
              onChange={setAnalysisPromptId}
              options={analysisPrompts.map(p => ({
                value: p.id,
                label: p.name,
                description: `Version ${p.version}`
              }))}
              placeholder="Select a prompt..."
            />
            {analysisPrompts.length === 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                No thumbnail prompts found. Create one in System Prompts with category "thumbnails".
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} className="mt-2" />
            <Button
              icon={analyzing ? Loader2 : Camera}
              onClick={handleAnalyze}
              disabled={analyzing || !analysisPromptId}
              className={cn("shrink-0 py-2.5", analyzing && "[&_svg]:animate-spin")}
            >
              {analyzing ? 'Identifying...' : 'Identify Moments'}
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
      {videoSummary && (
        <Card title="Video Summary">
          <p className="text-sm leading-relaxed">{videoSummary}</p>
        </Card>
      )}

      {hasScreenshots && (
        <ThumbnailsScreenshotGrid
          screenshots={screenshots}
          capturing={capturing}
          captureProgress={captureProgress}
        />
      )}

      {/* Section 3: Collage Generation */}
      {showCollageSection && !thumbnailUrl && (
        <div className="flex items-end gap-4">
          <div className="flex-1 min-w-0">
            <Select
              label="Collage Prompt"
              value={collagePromptId}
              onChange={setCollagePromptId}
              options={collagePrompts.map(p => ({
                value: p.id,
                label: p.name,
                description: `Version ${p.version}`
              }))}
              placeholder="Select a collage prompt..."
            />
            {collagePrompts.length === 0 && (
              <p className="text-xs text-muted-foreground mt-1">
                No collage prompts found. Create one in System Prompts with category "collage".
              </p>
            )}
          </div>
          <Button
            icon={generatingCollage ? Loader2 : Sparkles}
            onClick={handleGenerateCollage}
            disabled={generatingCollage || !collagePromptId || capturing}
            className={cn("shrink-0 py-2.5", generatingCollage && "[&_svg]:animate-spin")}
          >
            {generatingCollage ? 'Generating...' : 'Generate Thumbnail (2 credits)'}
          </Button>
        </div>
      )}

      {showResultSection && thumbnailUrl && <ThumbnailsResult thumbnailUrl={thumbnailUrl} />}
      {id && <div className="mt-6"><ServicesUsedPanel feature="thumbnails" recordId={id} /></div>}
    </motion.div>
  )
}
