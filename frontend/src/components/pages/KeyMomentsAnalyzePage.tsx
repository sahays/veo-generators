import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Upload, Zap, Loader2, Play, Clock, Tag, ArrowLeft,
  Film, FileVideo, ChevronRight,
} from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { KeyMoment, KeyMomentsAnalysis, SystemResource, KeyMomentsRecord, CompletedProductionSource } from '@/types/project'

function parseTimestamp(ts: string): number {
  const parts = ts.split(':').map(Number)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return Number(ts) || 0
}

function formatTimestamp(ts: string): string {
  const secs = parseTimestamp(ts)
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
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

type VideoSourceTab = 'productions' | 'past-uploads' | 'upload-new'

export const KeyMomentsAnalyzePage = () => {
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
  const [pastUploads, setPastUploads] = useState<KeyMomentsRecord[]>([])
  const [loadingSources, setLoadingSources] = useState(false)

  // Upload state
  const [uploading, setUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)

  // Prompt state
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')

  // Analysis state
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<KeyMomentsAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)

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
        setVideoUrl(record.video_signed_url || null)
        setGcsUri(record.video_gcs_uri)
        setVideoFilename(record.video_filename)
        setVideoSource(record.video_source)
        setProductionId(record.production_id)
        setAnalysis({
          key_moments: record.key_moments,
          video_summary: record.video_summary,
        })
      })
      .catch((err) => setError(err.message || 'Failed to load analysis'))
      .finally(() => setLoadingRecord(false))
  }, [id])

  // Load source data when tabs are shown (fresh mode only)
  useEffect(() => {
    if (isViewMode || videoUrl) return
    setLoadingSources(true)
    Promise.all([
      api.keyMoments.listProductionSources().catch(() => []),
      api.keyMoments.list().catch(() => []),
    ])
      .then(([prods, records]) => {
        setProductions(prods)
        setPastUploads(records.filter((r: KeyMomentsRecord) => r.video_source === 'upload'))
      })
      .finally(() => setLoadingSources(false))
  }, [isViewMode, videoUrl])

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

  const handleUpload = async (file: File) => {
    setError(null)
    setAnalysis(null)
    setUploading(true)
    try {
      const result = await api.assets.upload(file)
      setGcsUri(result.gcs_uri)
      setVideoUrl(result.signed_url)
      setVideoFilename(file.name)
      setVideoSource('upload')
      setProductionId(undefined)
    } catch (e: any) {
      setError(e.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('video/')) handleUpload(file)
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleUpload(file)
  }

  const handleSelectProduction = (prod: CompletedProductionSource) => {
    setVideoUrl(prod.video_signed_url)
    setGcsUri(prod.final_video_url)
    setVideoFilename(prod.name)
    setVideoSource('production')
    setProductionId(prod.id)
    setAnalysis(null)
    setError(null)
  }

  const handleSelectPastUpload = (record: KeyMomentsRecord) => {
    // Navigate to view the existing analysis
    navigate(`/key-moments/${record.id}`)
  }

  const handleChangeVideo = () => {
    setVideoUrl(null)
    setGcsUri(null)
    setVideoFilename('')
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
      })
      setAnalysis(result.data)
      // If we got an ID back, update the URL so refresh works
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

  const tabs: { key: VideoSourceTab; label: string; icon: typeof Film }[] = [
    { key: 'productions', label: 'Productions', icon: Film },
    { key: 'past-uploads', label: 'Past Uploads', icon: FileVideo },
    { key: 'upload-new', label: 'Upload New', icon: Upload },
  ]

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

      <div>
        <h2 className="text-2xl font-heading text-foreground tracking-tight">
          {isViewMode ? 'Key Moments Analysis' : 'Find Key Moments'}
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          {isViewMode
            ? `Viewing analysis for ${videoFilename || 'video'}`
            : 'Select a video source and let AI identify the key moments.'}
        </p>
      </div>

      {/* Video Source Selection (fresh mode, no video selected) */}
      {!isViewMode && !videoUrl && (
        <Card className="overflow-visible">
          {/* Tab bar */}
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

          {/* Tab content */}
          <div className="px-5 pb-5">
            {loadingSources ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="animate-spin text-accent" size={24} />
              </div>
            ) : (
              <>
                {/* Productions tab */}
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

                {/* Past Uploads tab */}
                {sourceTab === 'past-uploads' && (
                  <div>
                    {pastUploads.length === 0 ? (
                      <p className="text-xs text-muted-foreground py-8 text-center">
                        No past uploads found. Upload a video to get started.
                      </p>
                    ) : (
                      <div className="space-y-2">
                        {pastUploads.map((record) => (
                          <button
                            key={record.id}
                            onClick={() => handleSelectPastUpload(record)}
                            className="flex items-center gap-3 w-full p-3 rounded-lg border border-border bg-card hover:border-accent/50 hover:bg-accent/5 transition-all text-left cursor-pointer group"
                          >
                            <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center shrink-0">
                              <FileVideo size={16} className="text-accent-dark" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-medium text-foreground truncate group-hover:text-accent-dark transition-colors">
                                {record.video_filename || 'Untitled video'}
                              </p>
                              <p className="text-[10px] text-muted-foreground">
                                {record.moment_count} moments · {getTimeAgo(record.createdAt)}
                              </p>
                            </div>
                            <ChevronRight size={14} className="text-muted-foreground shrink-0" />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Upload New tab */}
                {sourceTab === 'upload-new' && (
                  <div
                    onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={handleDrop}
                    className={cn(
                      "aspect-video rounded-xl border-2 border-dashed flex flex-col items-center justify-center gap-4 transition-all cursor-pointer",
                      isDragging ? "border-accent bg-accent/5" : "border-border bg-muted/20 hover:border-accent/50",
                      uploading && "pointer-events-none opacity-60"
                    )}
                    onClick={() => document.getElementById('video-input')?.click()}
                  >
                    {uploading ? (
                      <>
                        <Loader2 className="animate-spin text-accent" size={32} />
                        <p className="text-sm text-muted-foreground">Uploading video...</p>
                      </>
                    ) : (
                      <>
                        <Upload size={32} className="text-muted-foreground" />
                        <div className="text-center">
                          <p className="text-sm font-medium text-foreground">Drop a video here or click to browse</p>
                          <p className="text-xs text-muted-foreground mt-1">MP4, MOV, WebM supported</p>
                        </div>
                      </>
                    )}
                    <input
                      id="video-input"
                      type="file"
                      accept="video/*"
                      className="hidden"
                      onChange={handleFileSelect}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </Card>
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
          <Button
            icon={analyzing ? Loader2 : Zap}
            onClick={handleAnalyze}
            disabled={analyzing || !promptId}
            className={cn(analyzing && "[&_svg]:animate-spin")}
          >
            {analyzing ? 'Analyzing...' : 'Analyze Video'}
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
      {analysis?.video_summary && (
        <Card title="Video Summary">
          <p className="text-sm leading-relaxed">{analysis.video_summary}</p>
        </Card>
      )}

      {/* Key Moments Grid */}
      {analysis && analysis.key_moments.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Clock size={16} className="text-accent-dark" />
            <h3 className="text-base font-heading font-bold text-foreground">
              {analysis.key_moments.length} Key Moments
            </h3>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {analysis.key_moments.map((moment: KeyMoment, i: number) => (
              <motion.button
                key={i}
                onClick={() => seekToMoment(i)}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
                className={cn(
                  "text-left p-4 rounded-xl border transition-all cursor-pointer",
                  "hover:border-accent/50 hover:bg-accent/5",
                  activeMomentIndex === i
                    ? "border-accent bg-accent/10 shadow-md ring-2 ring-accent/20"
                    : "border-border bg-card"
                )}
              >
                {/* Timestamp + Category */}
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-mono font-bold text-accent-dark bg-accent/10 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <Play size={8} className={cn(
                      activeMomentIndex === i ? "fill-accent-dark" : ""
                    )} />
                    {formatTimestamp(moment.timestamp_start)} - {formatTimestamp(moment.timestamp_end)}
                  </span>
                  {moment.category && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-600 border border-indigo-500/20">
                      {moment.category}
                    </span>
                  )}
                </div>

                {/* Title */}
                <p className="text-xs font-bold text-foreground line-clamp-1 mb-1">
                  {moment.title}
                </p>

                {/* Description */}
                <p className="text-[11px] text-muted-foreground line-clamp-3 leading-relaxed mb-2">
                  {moment.description}
                </p>

                {/* Tags */}
                {moment.tags && moment.tags.length > 0 && (
                  <div className="flex items-center gap-1 flex-wrap">
                    <Tag size={8} className="text-muted-foreground shrink-0" />
                    {moment.tags.map((tag, j) => (
                      <span key={j} className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </motion.button>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}
