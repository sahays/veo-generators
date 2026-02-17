import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Upload, Image, Loader2, ArrowLeft, Download,
  Film, FileVideo, ChevronRight, Camera, Sparkles, Tag,
} from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { ThumbnailRecord, ThumbnailScreenshot, SystemResource, CompletedProductionSource, UploadRecord } from '@/types/project'

function parseTimestamp(ts: string): number {
  const parts = ts.split(':').map(Number)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return Number(ts) || 0
}

function getTimeAgo(timestamp: string | number): string {
  const ms = typeof timestamp === 'string' ? new Date(timestamp).getTime() : timestamp
  if (isNaN(ms)) return ''
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

type VideoSourceTab = 'productions' | 'past-uploads'

export const ThumbnailsWorkPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isViewMode = !!id

  // Video source state
  const [sourceTab, setSourceTab] = useState<VideoSourceTab>('productions')
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [gcsUri, setGcsUri] = useState<string | null>(null)
  const [videoFilename, setVideoFilename] = useState('')
  const [videoSource, setVideoSource] = useState<'upload' | 'production'>('upload')
  const [productionId, setProductionId] = useState<string | undefined>()

  // Source data
  const [productions, setProductions] = useState<CompletedProductionSource[]>([])
  const [uploads, setUploads] = useState<UploadRecord[]>([])
  const [loadingSources, setLoadingSources] = useState(false)

  // Analysis prompt state
  const [analysisPrompts, setAnalysisPrompts] = useState<SystemResource[]>([])
  const [analysisPromptId, setAnalysisPromptId] = useState('')

  // Collage prompt state
  const [collagePrompts, setCollagePrompts] = useState<SystemResource[]>([])
  const [collagePromptId, setCollagePromptId] = useState('')

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
        setVideoUrl(record.video_signed_url || null)
        setGcsUri(record.video_gcs_uri)
        setVideoFilename(record.video_filename)
        setVideoSource(record.video_source)
        setProductionId(record.production_id)
        setVideoSummary(record.video_summary || null)
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

  // Load source data when tabs are shown (fresh mode only)
  useEffect(() => {
    if (isViewMode || videoUrl) return
    setLoadingSources(true)
    Promise.all([
      api.thumbnails.listProductionSources().catch(() => []),
      api.uploads.list({ file_type: 'video' }).catch(() => []),
    ])
      .then(([prods, uploadRecords]) => {
        setProductions(prods)
        setUploads(uploadRecords)
      })
      .finally(() => setLoadingSources(false))
  }, [isViewMode, videoUrl])

  const handleSelectProduction = (prod: CompletedProductionSource) => {
    setVideoUrl(prod.video_signed_url)
    setGcsUri(prod.final_video_url)
    setVideoFilename(prod.name)
    setVideoSource('production')
    setProductionId(prod.id)
    setScreenshots([])
    setThumbnailUrl(null)
    setError(null)
  }

  const handleSelectUpload = (record: UploadRecord) => {
    setVideoUrl(record.signed_url || null)
    setGcsUri(record.gcs_uri)
    setVideoFilename(record.filename)
    setVideoSource('upload')
    setProductionId(undefined)
    setScreenshots([])
    setThumbnailUrl(null)
    setError(null)
  }

  const handleChangeVideo = () => {
    setVideoUrl(null)
    setGcsUri(null)
    setVideoFilename('')
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

  const tabs: { key: VideoSourceTab; label: string; icon: typeof Film }[] = [
    { key: 'productions', label: 'Productions', icon: Film },
    { key: 'past-uploads', label: 'Files', icon: FileVideo },
  ]

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
          <h2 className="text-2xl font-heading text-foreground tracking-tight">
            {isViewMode ? 'Thumbnail Details' : 'Create Thumbnail'}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {isViewMode
              ? `Viewing thumbnail for ${videoFilename || 'video'}`
              : 'Select a video, identify key moments, then generate a collage thumbnail.'}
          </p>
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

      {/* Video Source Selection (fresh mode, no video selected) */}
      {!isViewMode && !videoUrl && (
        <Card className="overflow-visible">
          <div className="px-5 pt-5 pb-3">
            <div className="flex gap-1 bg-muted/50 rounded-lg p-1">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setSourceTab(tab.key)}
                  className={cn(
                    "flex items-center gap-1.5 flex-1 justify-center px-3 py-2 rounded-md text-xs font-medium transition-all cursor-pointer",
                    sourceTab === tab.key
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <tab.icon size={14} />
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="px-5 pb-5">
            {loadingSources ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="animate-spin text-accent" size={24} />
              </div>
            ) : (
              <>
                {sourceTab === 'productions' && (
                  <div>
                    {productions.length === 0 ? (
                      <p className="text-xs text-muted-foreground py-8 text-center">
                        No completed productions with video found.
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {productions.map((prod) => (
                          <button
                            key={prod.id}
                            onClick={() => handleSelectProduction(prod)}
                            className="flex items-center gap-3 p-3 rounded-lg border border-border bg-card hover:border-accent/50 hover:bg-accent/5 transition-all text-left cursor-pointer group"
                          >
                            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center shrink-0">
                              <Film size={16} className="text-indigo-600" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-medium text-foreground truncate group-hover:text-accent-dark transition-colors">
                                {prod.name}
                              </p>
                              <p className="text-[10px] text-muted-foreground">
                                {prod.type}
                              </p>
                            </div>
                            <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {sourceTab === 'past-uploads' && (
                  <div>
                    {uploads.length === 0 ? (
                      <div className="text-center py-8">
                        <p className="text-xs text-muted-foreground mb-2">
                          No video files found.
                        </p>
                        <button
                          onClick={() => navigate('/uploads')}
                          className="text-xs text-accent hover:text-accent-dark transition-colors"
                        >
                          Go to Files to add videos
                        </button>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {uploads.map((record) => (
                          <button
                            key={record.id}
                            onClick={() => handleSelectUpload(record)}
                            className="flex items-center gap-3 w-full p-3 rounded-lg border border-border bg-card hover:border-accent/50 hover:bg-accent/5 transition-all text-left cursor-pointer group"
                          >
                            <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
                              <FileVideo size={16} className="text-accent-dark" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-medium text-foreground truncate group-hover:text-accent-dark transition-colors">
                                {record.filename}
                              </p>
                              <p className="text-[10px] text-muted-foreground">
                                {formatFileSize(record.file_size_bytes)}
                                {record.resolution_label && ` · ${record.resolution_label}`}
                                {' · '}{getTimeAgo(record.createdAt)}
                              </p>
                            </div>
                            <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </Card>
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
          <Button
            icon={analyzing ? Loader2 : Camera}
            onClick={handleAnalyze}
            disabled={analyzing || !analysisPromptId}
            className={cn("shrink-0 py-2.5", analyzing && "[&_svg]:animate-spin")}
          >
            {analyzing ? 'Identifying...' : 'Identify Moments'}
          </Button>
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

      {/* Section 2: Screenshots Grid */}
      {hasScreenshots && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Camera size={16} className="text-accent-dark" />
            <h3 className="text-base font-heading font-bold text-foreground">
              {screenshots.length} Screenshots {capturing ? 'Capturing...' : 'Captured'}
            </h3>
            {capturing && (
              <span className="text-xs text-muted-foreground">
                ({captureProgress}/{screenshots.length})
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {screenshots.map((screenshot, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="rounded-xl border border-border bg-card overflow-hidden"
              >
                {/* Screenshot image */}
                <div className="aspect-video bg-black relative">
                  {screenshot.localUrl ? (
                    <img
                      src={screenshot.localUrl}
                      alt={screenshot.title}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <Loader2 className="animate-spin text-accent" size={20} />
                    </div>
                  )}
                  {/* Timestamp badge */}
                  <span className="absolute top-2 left-2 text-[9px] font-mono font-bold text-white bg-black/70 px-1.5 py-0.5 rounded">
                    {screenshot.timestamp}
                  </span>
                </div>

                {/* Info */}
                <div className="p-3 space-y-1.5">
                  <p className="text-xs font-bold text-foreground line-clamp-1">
                    {screenshot.title}
                  </p>
                  <p className="text-[10px] text-muted-foreground line-clamp-2 leading-relaxed">
                    {screenshot.visual_characteristics}
                  </p>
                  {screenshot.tags && screenshot.tags.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <Tag size={8} className="text-muted-foreground shrink-0" />
                      {screenshot.tags.slice(0, 3).map((tag, j) => (
                        <span key={j} className="text-[8px] px-1 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </div>
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
            {generatingCollage ? 'Generating...' : 'Generate Thumbnail'}
          </Button>
        </div>
      )}

      {/* Section 4: Result */}
      {showResultSection && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Image size={16} className="text-accent-dark" />
            <h3 className="text-base font-heading font-bold text-foreground">
              Generated Thumbnail
            </h3>
          </div>

          <div className="rounded-2xl overflow-hidden border border-border shadow-2xl" style={{ aspectRatio: '16/9' }}>
            <img
              src={thumbnailUrl}
              alt="Generated thumbnail"
              className="w-full h-full object-cover"
            />
          </div>

          <div className="flex justify-end">
            <a
              href={thumbnailUrl}
              download="thumbnail.png"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-accent-foreground text-sm font-medium hover:bg-accent/90 transition-colors"
            >
              <Download size={16} />
              Download Thumbnail
            </a>
          </div>
        </div>
      )}
    </motion.div>
  )
}
