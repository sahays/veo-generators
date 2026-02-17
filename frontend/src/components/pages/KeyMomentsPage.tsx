import { useState, useRef, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Upload, Zap, Loader2, Play, Clock, Tag } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { KeyMoment, KeyMomentsAnalysis, SystemResource } from '@/types/project'

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

export const KeyMomentsPage = () => {
  // Upload state
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [gcsUri, setGcsUri] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)

  // Prompt state
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [promptId, setPromptId] = useState('')

  // Analysis state
  const [analyzing, setAnalyzing] = useState(false)
  const [analysis, setAnalysis] = useState<KeyMomentsAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Player state
  const videoRef = useRef<HTMLVideoElement>(null)
  const [activeMomentIndex, setActiveMomentIndex] = useState<number | null>(null)

  // Fetch key-moments prompts on mount
  useEffect(() => {
    api.system.listResources('prompt', 'key-moments').then(setPrompts).catch(console.error)
  }, [])

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
    setVideoFile(file)
    setError(null)
    setAnalysis(null)
    setUploading(true)
    try {
      const result = await api.assets.upload(file)
      setGcsUri(result.gcs_uri)
      setVideoUrl(result.signed_url)
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

  const handleAnalyze = async () => {
    if (!gcsUri || !promptId) return
    setAnalyzing(true)
    setError(null)
    try {
      const result = await api.keyMoments.analyze({ gcs_uri: gcsUri, prompt_id: promptId })
      setAnalysis(result.data)
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
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      className="max-w-5xl mx-auto space-y-8 pb-20"
    >
      <div>
        <h2 className="text-2xl font-heading text-foreground tracking-tight">Key Moments</h2>
        <p className="text-sm text-muted-foreground mt-1">Upload a video and let AI identify the key moments with timestamps.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left: Video Player */}
        <div className="lg:col-span-2 space-y-6">
          {!videoUrl ? (
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              className={cn(
                "aspect-video rounded-2xl border-2 border-dashed flex flex-col items-center justify-center gap-4 transition-all cursor-pointer",
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
          ) : (
            <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
              <video
                ref={videoRef}
                controls
                className="w-full h-full"
                src={videoUrl}
              />
            </div>
          )}

          {analysis?.video_summary && (
            <Card title="Video Summary">
              <p className="text-sm leading-relaxed">{analysis.video_summary}</p>
            </Card>
          )}
        </div>

        {/* Right: Controls + Results */}
        <div className="space-y-6">
          {videoUrl && (
            <Card title="Analyze" icon={Zap}>
              <div className="space-y-4">
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
                  <p className="text-xs text-muted-foreground">
                    No key-moments prompts found. Create one in System Prompts with category "Key Moments Analysis".
                  </p>
                )}
                <Button
                  icon={analyzing ? Loader2 : Zap}
                  onClick={handleAnalyze}
                  disabled={analyzing || !promptId}
                  className={cn("w-full justify-center", analyzing && "[&_svg]:animate-spin")}
                >
                  {analyzing ? 'Analyzing...' : 'Analyze Video'}
                </Button>
              </div>
            </Card>
          )}

          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
              {error}
            </div>
          )}

          {analysis && analysis.key_moments.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Clock size={16} className="text-accent-dark" />
                <h3 className="text-sm font-heading font-bold text-foreground">
                  {analysis.key_moments.length} Key Moments
                </h3>
              </div>
              <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
                {analysis.key_moments.map((moment: KeyMoment, i: number) => (
                  <motion.button
                    key={i}
                    onClick={() => seekToMoment(i)}
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className={cn(
                      "w-full text-left p-3 rounded-xl border transition-all cursor-pointer",
                      "hover:border-accent/50 hover:bg-accent/5",
                      activeMomentIndex === i
                        ? "border-accent bg-accent/10 shadow-sm"
                        : "border-border bg-card"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex items-center gap-1 shrink-0 mt-0.5">
                        <Play size={10} className={cn(
                          "transition-colors",
                          activeMomentIndex === i ? "text-accent-dark fill-accent-dark" : "text-muted-foreground"
                        )} />
                        <span className="text-[10px] font-mono font-bold text-accent-dark bg-accent/10 px-1.5 py-0.5 rounded">
                          {formatTimestamp(moment.timestamp_start)}
                        </span>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-foreground truncate">{moment.title}</p>
                        <p className="text-[10px] text-muted-foreground line-clamp-2 mt-0.5">{moment.description}</p>
                        {moment.tags && moment.tags.length > 0 && (
                          <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                            <Tag size={8} className="text-muted-foreground shrink-0" />
                            {moment.tags.map((tag, j) => (
                              <span key={j} className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}
