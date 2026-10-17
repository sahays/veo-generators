import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Camera, Check, Loader2, Pencil, Sparkles, Upload } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/UI'
import { ModelPill } from '@/components/ModelPill'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { api } from '@/hooks/useApiClient'
import { cn } from '@/lib/utils'
import { captureVideoFrames } from '@/lib/captureFrames'
import { ThumbnailsResult } from '@/components/pages/thumbnails/components/ThumbnailsResult'
import { ThumbnailsScreenshotGrid } from '@/components/pages/thumbnails/components/ThumbnailsScreenshotGrid'
import type { SystemResource, ThumbnailScreenshot } from '@/types/project'

export type ScreenshotWithLocal = ThumbnailScreenshot & { localUrl?: string }

export interface AnalyzeMomentInput {
  timestamp_start: string
  timestamp_end: string
  title?: string
  description?: string
  visual_characteristics?: string
  category?: string
  tags?: string[]
}

export function mapMomentsToScreenshots(moments: AnalyzeMomentInput[]): ScreenshotWithLocal[] {
  return moments.map((m) => ({
    timestamp: `${m.timestamp_start}-${m.timestamp_end}`,
    title: m.title || '',
    description: m.description || '',
    visual_characteristics: m.visual_characteristics || '',
    category: m.category || '',
    tags: m.tags || [],
    gcs_uri: '',
    localUrl: undefined,
  }))
}

export async function runScreenshotCapture(params: {
  video: HTMLVideoElement | null
  canvas: HTMLCanvasElement | null
  rid: string
  moments: { timestamp_start: string; timestamp_end: string }[]
  setCapturing: (v: boolean) => void
  setCaptureProgress: (v: number) => void
  setScreenshots: React.Dispatch<React.SetStateAction<ScreenshotWithLocal[]>>
  setRecordStatus: (v: string) => void
}) {
  const { video, canvas, rid, moments, setCapturing, setCaptureProgress, setScreenshots, setRecordStatus } = params
  if (!video || !canvas || !rid) return
  setCapturing(true)
  setCaptureProgress(0)
  const captured = await captureVideoFrames(video, canvas, moments, (frame) => {
    setScreenshots((prev) => {
      const updated = [...prev]
      if (updated[frame.index]) {
        updated[frame.index] = {
          ...updated[frame.index],
          gcs_uri: frame.gcs_uri,
          localUrl: frame.signed_url,
        }
      }
      return updated
    })
    setCaptureProgress(frame.index + 1)
  })
  if (captured.length > 0) {
    await api.thumbnails.saveScreenshots(
      rid,
      captured.map((c) => ({ index: c.index, gcs_uri: c.gcs_uri })),
    )
    setRecordStatus('screenshots_ready')
  }
  setCapturing(false)
}

export const ThumbnailsPageHeader = ({
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
  setVideoFilename: (v: string) => void
  modelName?: string
  showAddFiles: boolean
  onNavigateUploads: () => void
}) => {
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  return (
    <>
      <div className="flex items-center gap-3">
        <Link to="/thumbnails" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={14} /> Back to Thumbnails
        </Link>
      </div>
      <div className="flex items-center justify-between">
        <div>
          {isViewMode ? (
            <>
              {isEditingName ? (
                <form
                  className="flex items-center gap-2"
                  onSubmit={async (e) => {
                    e.preventDefault()
                    if (id) await api.thumbnails.update(id, { display_name: editName })
                    setVideoFilename(editName)
                    setIsEditingName(false)
                  }}
                >
                  <Input
                    autoFocus
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="h-9 text-2xl font-heading font-bold text-foreground bg-muted px-2 py-0.5"
                  />
                  <Button type="submit" variant="ghost" size="icon" className="h-7 w-7 text-accent hover:text-accent-dark">
                    <Check size={16} />
                  </Button>
                </form>
              ) : canWrite ? (
                <Button
                  variant="unstyled"
                  className="flex items-center gap-2 text-2xl font-heading text-foreground tracking-tight hover:text-accent-dark transition-colors"
                  onClick={() => {
                    setEditName(videoFilename || '')
                    setIsEditingName(true)
                  }}
                >
                  {videoFilename || 'Untitled'}
                  <Pencil size={12} className="text-muted-foreground" />
                </Button>
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
              <p className="text-sm text-muted-foreground mt-1">
                Select a video, identify key moments, then generate a collage thumbnail.
              </p>
            </>
          )}
        </div>
        {showAddFiles && (
          <Button variant="secondary" size="sm" icon={Upload} onClick={onNavigateUploads}>
            Add Files
          </Button>
        )}
      </div>
    </>
  )
}

export const ThumbnailAnalyzeControls = ({
  analysisPrompts,
  analysisPromptId,
  setAnalysisPromptId,
  modelConfig,
  setModelConfig,
  analyzing,
  onAnalyze,
}: {
  analysisPrompts: SystemResource[]
  analysisPromptId: string
  setAnalysisPromptId: (v: string) => void
  modelConfig: { modelId?: string; region?: string }
  setModelConfig: (v: { modelId?: string; region?: string }) => void
  analyzing: boolean
  onAnalyze: () => void
}) => (
  <div className="space-y-1.5">
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex-1 min-w-[220px]">
        <Select
          label="Thumbnail Analysis Prompt"
          value={analysisPromptId}
          onChange={setAnalysisPromptId}
          options={analysisPrompts.map((p) => ({
            value: p.id,
            label: p.name,
            description: `Version ${p.version}`,
          }))}
          placeholder="Select a prompt..."
        />
      </div>
      <ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />
      <Button
        icon={analyzing ? Loader2 : Camera}
        onClick={onAnalyze}
        disabled={analyzing || !analysisPromptId}
        className={cn('shrink-0 py-2.5', analyzing && '[&_svg]:animate-spin')}
      >
        {analyzing ? 'Identifying...' : 'Identify Moments'}
      </Button>
    </div>
    {analysisPrompts.length === 0 && (
      <p className="text-xs text-muted-foreground">
        No thumbnail prompts found. Create one in System Prompts with category &quot;thumbnails&quot;.
      </p>
    )}
  </div>
)

export const ThumbnailCollageControls = ({
  collagePrompts,
  collagePromptId,
  setCollagePromptId,
  generatingCollage,
  capturing,
  onGenerateCollage,
}: {
  collagePrompts: SystemResource[]
  collagePromptId: string
  setCollagePromptId: (v: string) => void
  generatingCollage: boolean
  capturing: boolean
  onGenerateCollage: () => void
}) => (
  <div className="flex items-end gap-4">
    <div className="flex-1 min-w-0">
      <Select
        label="Collage Prompt"
        value={collagePromptId}
        onChange={setCollagePromptId}
        options={collagePrompts.map((p) => ({
          value: p.id,
          label: p.name,
          description: `Version ${p.version}`,
        }))}
        placeholder="Select a collage prompt..."
      />
      {collagePrompts.length === 0 && (
        <p className="text-xs text-muted-foreground mt-1">
          No collage prompts found. Create one in System Prompts with category &quot;collage&quot;.
        </p>
      )}
    </div>
    <Button
      icon={generatingCollage ? Loader2 : Sparkles}
      onClick={onGenerateCollage}
      disabled={generatingCollage || !collagePromptId || capturing}
      className={cn('shrink-0 py-2.5', generatingCollage && '[&_svg]:animate-spin')}
    >
      {generatingCollage ? 'Generating...' : 'Generate Thumbnail (2 credits)'}
    </Button>
  </div>
)

export const ThumbnailOutputSections = ({
  id,
  error,
  videoSummary,
  screenshots,
  capturing,
  captureProgress,
  showCollageSection,
  thumbnailUrl,
  showResultSection,
  collagePrompts,
  collagePromptId,
  setCollagePromptId,
  generatingCollage,
  onGenerateCollage,
}: {
  id?: string
  error: string | null
  videoSummary: string | null
  screenshots: ScreenshotWithLocal[]
  capturing: boolean
  captureProgress: number
  showCollageSection: boolean
  thumbnailUrl: string | null
  showResultSection: boolean
  collagePrompts: SystemResource[]
  collagePromptId: string
  setCollagePromptId: (v: string) => void
  generatingCollage: boolean
  onGenerateCollage: () => void
}) => (
  <>
    {error && (
      <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">{error}</div>
    )}
    {videoSummary && (
      <Card title="Video Summary">
        <p className="text-sm leading-relaxed">{videoSummary}</p>
      </Card>
    )}
    {screenshots.length > 0 && (
      <ThumbnailsScreenshotGrid screenshots={screenshots} capturing={capturing} captureProgress={captureProgress} />
    )}
    {showCollageSection && !thumbnailUrl && (
      <ThumbnailCollageControls
        collagePrompts={collagePrompts}
        collagePromptId={collagePromptId}
        setCollagePromptId={setCollagePromptId}
        generatingCollage={generatingCollage}
        capturing={capturing}
        onGenerateCollage={onGenerateCollage}
      />
    )}
    {showResultSection && thumbnailUrl && <ThumbnailsResult thumbnailUrl={thumbnailUrl} />}
    {id && (
      <div className="mt-6">
        <ServicesUsedPanel feature="thumbnails" recordId={id} />
      </div>
    )}
  </>
)
