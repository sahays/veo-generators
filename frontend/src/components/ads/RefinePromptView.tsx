import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Sparkles, Play,
  RotateCcw, Loader2, LayoutGrid, List, Plus, Lock, AlertCircle,
  Cpu, Volume2, Video, Image as ImageIcon, Globe, Clock,
  ShieldCheck, CheckCircle2, ChevronDown, ChevronUp, RefreshCw, Wand2, Film,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { CostBreakdownPill } from '@/components/ads/CostBreakdownPill'
import { ErrorBadge } from '@/components/ads/ErrorBadge'
import { SceneItem } from '@/components/ads/SceneItem'
import {
  EvalStatusPill,
  RenderQualityBadge,
  SceneMetaBanner,
  StepStatusIcon,
  StepUsageBadges,
} from '@/components/ads/SceneItemShared'
import { useProjectStore } from '@/store/useProjectStore'
import { useAuthStore } from '@/store/useAuthStore'

import {
  PRODUCTION_LANGUAGES,
  type PipelineStepLog,
  type ProductionLanguage,
  type Project,
  type RenderQuality,
  type Scene,
  type VideoResolution,
} from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

const ACTIVE_PIPELINE_STATUSES = [
  'reviewing',
  'generating',
  'stitching',
  'evaluating',
  'regenerating',
]

export const RefinePromptView = () => {
  const { tempProjectData, updateScene, addScene, setActiveProject, setTempProjectData } = useProjectStore()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [layout, setLayout] = useState<'grid' | 'list'>('list')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [isStartingRender, setIsStartingRender] = useState(false)
  const [isReviewingContinuity, setIsReviewingContinuity] = useState(false)
  const [isEvaluatingVideo, setIsEvaluatingVideo] = useState(false)
  const [isRegeneratingFlagged, setIsRegeneratingFlagged] = useState(false)
  const [toastBanner, setToastBanner] = useState<string | null>(null)
  const [showReviewDetails, setShowReviewDetails] = useState(false)
  const [showEvalDetails, setShowEvalDetails] = useState(false)
  const [modelDefaults, setModelDefaults] = useState<Record<string, any> | null>(null)
  const analyzeCalledRef = useRef(false)

  useEffect(() => {
    api.models.defaults().then(setModelDefaults).catch(() => {})
  }, [])

  // On mount: load production from API if we don't have matching tempProjectData
  useEffect(() => {
    if (id && (!tempProjectData || (tempProjectData as any)?.id !== id)) {
      api.projects.get(id).then((p) => {
        if (p && p.id) {
          analyzeCalledRef.current = false
          setTempProjectData({ ...p, scenes: p.scenes || [] })
          setActiveProject(id)
        }
      }).catch(() => {
        setAnalysisError('Failed to load production')
      })
    }
  }, [id])

  const production = tempProjectData as unknown as Project | null
  const currentStatus = production?.status
  const isRendering = !!currentStatus && ACTIVE_PIPELINE_STATUSES.includes(currentStatus)
  const isReadOnly = isRendering || !canWrite
  const scenes = tempProjectData?.scenes || []
  const productionId = production?.id || id || ''

  // Call real Gemini analysis if no scenes exist
  useEffect(() => {
    if (scenes.length > 0 || isAnalyzing || isReadOnly || !tempProjectData || analyzeCalledRef.current) return
    if (!productionId) return

    analyzeCalledRef.current = true
    setIsAnalyzing(true)
    setAnalysisError(null)

    const promptId = tempProjectData.prompt_id
    const overrides = {
      name: tempProjectData.name,
      type: tempProjectData.type,
      base_concept: tempProjectData.base_concept,
      video_length: tempProjectData.video_length,
      orientation: tempProjectData.orientation,
      language: (tempProjectData as any).language || 'en-IN',
    }

    api.projects.analyze(productionId, promptId, undefined, undefined, undefined, overrides)
      .then((result) => {
        const scenesData = Array.isArray(result.data) ? result.data : (result.data?.scenes || [])
        const newScenes: Scene[] = scenesData.map((s: any, i: number) => ({
          id: s.id || `s-${i}`,
          visual_description: s.visual_description,
          narration: s.narration,
          narration_enabled: !!s.narration,
          music_description: s.music_description,
          music_enabled: !!s.music_description,
          speaker_notes: s.speaker_notes,
          timestamp_start: s.timestamp_start,
          timestamp_end: s.timestamp_end,
          metadata: s.metadata || {},
          thumbnail_url: s.thumbnail_url,
          tokens_consumed: s.usage ? { input: s.usage.input_tokens || 0, output: s.usage.output_tokens || 0 } : undefined,
        }))
        setTempProjectData({
          ...tempProjectData,
          scenes: newScenes,
          total_usage: result.usage || (tempProjectData as any)?.total_usage,
        } as any)
        setIsAnalyzing(false)
      })
      .catch((err) => {
        console.error('Analysis failed:', err)
        const detail = err instanceof Error ? err.message : String(err)
        setAnalysisError(`Gemini analysis failed: ${detail}`)
        setIsAnalyzing(false)
      })
  }, [scenes.length, isAnalyzing, isReadOnly, tempProjectData, productionId, setTempProjectData])

  const showToast = (msg: string) => {
    setToastBanner(msg)
    setTimeout(() => setToastBanner(null), 6000)
  }

  const handleReviewContinuity = async () => {
    if (!productionId || scenes.length === 0) return
    setIsReviewingContinuity(true)
    setGenerateError(null)
    try {
      const updated = await api.projects.reviewStoryboard(productionId)
      const fresh = updated?.id ? updated : await api.projects.get(productionId)
      if (fresh) {
        setTempProjectData({ ...fresh, scenes: fresh.scenes || [] } as any)
        const score = fresh.review_report?.overall_score ?? 100
        const count = fresh.review_report?.issues?.length ?? 0
        showToast(`Continuity Review complete: Score ${score}/100 (${count} issue${count === 1 ? '' : 's'} auto-fixed)`)
        setShowReviewDetails(true)
      }
    } catch (err) {
      console.error('Continuity review failed:', err)
      setGenerateError(err instanceof Error ? err.message : 'Continuity review failed')
    } finally {
      setIsReviewingContinuity(false)
    }
  }

  const handleGenerateAll = async (
    quality: RenderQuality = 'draft',
    resolution: VideoResolution = '360p',
  ) => {
    if (!productionId || scenes.length === 0) return
    setIsStartingRender(true)
    setGenerateError(null)
    try {
      await api.projects.render(productionId, {
        quality,
        resolution,
        auto_review: quality === 'draft',
        auto_eval: true,
      })
      const updated = await api.projects.get(productionId)
      if (updated) setTempProjectData({ ...updated, scenes: updated.scenes || [] } as any)
    } catch (err) {
      console.error('Failed to start render:', err)
      setGenerateError(err instanceof Error ? err.message : 'Failed to start generation')
    } finally {
      setIsStartingRender(false)
    }
  }

  const handleEvaluateVideo = async () => {
    if (!productionId) return
    setIsEvaluatingVideo(true)
    setGenerateError(null)
    try {
      const updated = await api.projects.evaluateVideo(productionId)
      const fresh = updated?.id ? updated : await api.projects.get(productionId)
      if (fresh) {
        setTempProjectData({ ...fresh, scenes: fresh.scenes || [] } as any)
        const score = fresh.eval_report?.overall_score ?? 0
        showToast(`Video Evaluation complete: Score ${score}/100 (${fresh.eval_report?.passed ? 'Passed' : 'Flagged for regeneration'})`)
        setShowEvalDetails(true)
      }
    } catch (err) {
      console.error('Video evaluation failed:', err)
      setGenerateError(err instanceof Error ? err.message : 'Video evaluation failed')
    } finally {
      setIsEvaluatingVideo(false)
    }
  }

  const handleRegenerateFlagged = async () => {
    if (!productionId) return
    setIsRegeneratingFlagged(true)
    setGenerateError(null)
    try {
      await api.projects.regenerateFlagged(productionId)
      const updated = await api.projects.get(productionId)
      if (updated) setTempProjectData({ ...updated, scenes: updated.scenes || [] } as any)
      showToast('Started regenerating flagged scenes...')
    } catch (err) {
      console.error('Failed to regenerate flagged scenes:', err)
      setGenerateError(err instanceof Error ? err.message : 'Failed to regenerate flagged scenes')
    } finally {
      setIsRegeneratingFlagged(false)
    }
  }

  // Poll production status while any active pipeline stage is running
  useEffect(() => {
    if (!productionId || !isRendering) return

    const pollInterval = setInterval(async () => {
      try {
        const prod = await api.projects.get(productionId)
        if (!prod) return
        setTempProjectData({ ...prod, scenes: prod.scenes || [] } as any)

        if (!ACTIVE_PIPELINE_STATUSES.includes(prod.status)) {
          if (prod.status === 'failed') {
            setGenerateError((prod as any).error_message || 'Generation failed')
          }
          clearInterval(pollInterval)
        }
      } catch (err) {
        console.error('Poll failed:', err)
      }
    }, 5000)

    return () => clearInterval(pollInterval)
  }, [isRendering, productionId])

  const totalUsage = production?.total_usage
  const inputTokens = totalUsage?.input_tokens || 0
  const outputTokens = totalUsage?.output_tokens || 0
  const estimatedCost = totalUsage?.cost_usd || 0
  const imageGenerations = totalUsage?.image_generations || 0
  const imageCost = totalUsage?.image_cost_usd || 0
  const veoVideos = totalUsage?.veo_videos || 0
  const veoSeconds = totalUsage?.veo_seconds || 0
  const veoUnitCost = totalUsage?.veo_unit_cost || 0
  const veoCost = totalUsage?.veo_cost_usd || 0

  const pipelineSteps: PipelineStepLog[] = production?.pipeline_steps || []
  const reviewReport = production?.review_report
  const evalReport = production?.eval_report

  if (analysisError) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-6">
        <div className="w-20 h-20 rounded-full bg-red-500/10 flex items-center justify-center">
          <AlertCircle className="text-red-500" size={32} />
        </div>
        <div className="text-center space-y-2">
          <h3 className="text-xl font-heading font-bold text-red-500">Analysis Failed</h3>
          <p className="text-sm text-muted-foreground">{analysisError}</p>
        </div>
        <Button onClick={() => navigate(id ? `/productions/${id}/edit` : '/productions/new')} icon={ArrowLeft}>
          Go Back
        </Button>
      </div>
    )
  }

  if (isAnalyzing) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-6">
        <div className="relative">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
            className="w-20 h-20 border-2 border-accent border-t-transparent rounded-full"
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <Sparkles className="text-accent animate-pulse" size={24} />
          </div>
        </div>
        <div className="text-center space-y-2">
          <h3 className="text-xl font-heading font-bold">Generating Script...</h3>
          <p className="text-sm text-muted-foreground">Gemini is breaking your brief into cinematic scenes.</p>
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="max-w-6xl mx-auto space-y-6 pb-32"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 py-4 border-b border-border">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate(isReadOnly ? `/productions/${id}` : (id ? `/productions/${id}/edit` : '/productions/new'))}
          >
            <ArrowLeft size={20} />
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-heading text-foreground tracking-tight">Script Editor</h2>
              {production?.render_quality && (
                <RenderQualityBadge
                  quality={production.render_quality}
                  resolution={production.video_resolution}
                />
              )}
              {isReadOnly && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[9px] font-bold uppercase tracking-wider border border-border">
                  <Lock size={10} /> Read Only
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">Fine-tune each scene, run AI continuity checks, and render in Draft 360p or Final 720p HD.</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-1 bg-muted/50 p-1 rounded-[6px] border border-border">
            <Button
              variant={layout === 'list' ? 'primary' : 'ghost'}
              size="icon"
              onClick={() => setLayout('list')}
              className="h-7 w-7"
            >
              <List size={15} />
            </Button>
            <Button
              variant={layout === 'grid' ? 'primary' : 'ghost'}
              size="icon"
              onClick={() => setLayout('grid')}
              className="h-7 w-7"
            >
              <LayoutGrid size={15} />
            </Button>
          </div>

          <div className="hidden lg:flex items-center px-3 border-r border-border">
            <CostBreakdownPill
              inputTokens={inputTokens}
              outputTokens={outputTokens}
              totalCost={estimatedCost}
              imageGenerations={imageGenerations}
              imageCost={imageCost}
              veoVideos={veoVideos}
              veoSeconds={veoSeconds}
              veoUnitCost={veoUnitCost}
              veoCost={veoCost}
            />
          </div>

          {canWrite && !isRendering && (
            <Button
              variant="outline"
              size="sm"
              icon={isReviewingContinuity ? Loader2 : Wand2}
              onClick={handleReviewContinuity}
              disabled={isReviewingContinuity || scenes.length === 0}
            >
              {isReviewingContinuity ? 'Reviewing...' : 'Review Continuity'}
            </Button>
          )}

          {(() => {
            const s = currentStatus
            const completedScenes = scenes.filter((sc: any) => sc.status === 'completed' || !!sc.video_url).length
            const framesReady = scenes.filter((sc: any) => !!sc.thumbnail_url).length

            if (s === 'reviewing') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Reviewing Storyboard Continuity...
                </div>
              )
            }
            if (s === 'generating') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Generating ({framesReady}/{scenes.length} frames, {completedScenes}/{scenes.length} videos)
                </div>
              )
            }
            if (s === 'stitching') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Transcoding & Stitching Video...
                </div>
              )
            }
            if (s === 'evaluating') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Evaluating Stitched Video Quality...
                </div>
              )
            }
            if (s === 'regenerating') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Regenerating Flagged Scenes...
                </div>
              )
            }
            if (s === 'completed') {
              const isDraft = production?.render_quality === 'draft'
              return (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant={isDraft ? 'secondary' : 'primary'}
                    size="sm"
                    icon={Play}
                    onClick={() => navigate(`/productions/${id}`)}
                  >
                    {isDraft ? 'View Draft Video' : 'View Final Video'}
                  </Button>
                  {canWrite && isDraft && (
                    <Button
                      variant="primary"
                      size="sm"
                      icon={isStartingRender ? Loader2 : Sparkles}
                      onClick={() => handleGenerateAll('final', '720p')}
                      disabled={isStartingRender}
                    >
                      {isStartingRender ? 'Upgrading...' : 'Upgrade to Final (720p HD)'}
                    </Button>
                  )}
                  {canWrite && !isDraft && (
                    <Button
                      variant="outline"
                      size="sm"
                      icon={isStartingRender ? Loader2 : Film}
                      onClick={() => handleGenerateAll('draft', '360p')}
                      disabled={isStartingRender}
                    >
                      Re-render Draft (360p)
                    </Button>
                  )}
                </div>
              )
            }
            if (s === 'failed') {
              const errMsg = generateError || (tempProjectData as any)?.error_message || 'Generation failed'
              return (
                <div className="flex flex-wrap items-center gap-2.5">
                  <ErrorBadge message={errMsg} />
                  {canWrite && (
                    <>
                      <Button
                        variant="primary"
                        size="sm"
                        icon={isStartingRender ? Loader2 : RotateCcw}
                        onClick={() => handleGenerateAll('draft', '360p')}
                        disabled={isStartingRender}
                      >
                        {isStartingRender ? 'Starting...' : 'Retry Draft (360p)'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        icon={isStartingRender ? Loader2 : Sparkles}
                        onClick={() => handleGenerateAll('final', '720p')}
                        disabled={isStartingRender}
                      >
                        Generate Final (720p)
                      </Button>
                    </>
                  )}
                </div>
              )
            }
            if (!canWrite) return null
            return (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={isStartingRender ? Loader2 : Play}
                  onClick={() => handleGenerateAll('draft', '360p')}
                  disabled={isStartingRender}
                >
                  {isStartingRender ? 'Starting...' : 'Generate All (Draft 360p)'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  icon={isStartingRender ? Loader2 : Sparkles}
                  onClick={() => handleGenerateAll('final', '720p')}
                  disabled={isStartingRender}
                >
                  Generate Final (720p)
                </Button>
              </div>
            )
          })()}
        </div>
      </div>

      {toastBanner && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-xs font-medium text-emerald-400 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <CheckCircle2 size={14} />
            {toastBanner}
          </span>
          <Button variant="ghost" size="xs" onClick={() => setToastBanner(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {generateError && currentStatus !== 'failed' && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-xs font-medium text-red-400 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <AlertCircle size={14} />
            {generateError}
          </span>
          <Button variant="ghost" size="xs" onClick={() => setGenerateError(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {/* Active AI Models (Script, Storyboard, Audio & Video) + Duration & Language Controls */}
      <div className="rounded-xl border border-border bg-card/80 p-4 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/60 px-2.5 py-1 font-medium text-foreground">
              <Cpu size={13} className="text-accent" />
              <span className="text-muted-foreground">Script & Dialogue:</span>
              <span className="font-mono font-semibold">
                {totalUsage?.model_name || modelDefaults?.text?.code || 'gemini-3.8-flash'}
              </span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/60 px-2.5 py-1 font-medium text-foreground">
              <ImageIcon size={13} className="text-amber-500" />
              <span className="text-muted-foreground">Storyboard Frames:</span>
              <span className="font-mono font-semibold">
                {modelDefaults?.image?.code || 'gemini-nano-banana-2.1'}
              </span>
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/60 px-2.5 py-1 font-medium text-foreground">
              <Video size={13} className="text-emerald-500" />
              <Volume2 size={13} className="text-emerald-500" />
              <span className="text-muted-foreground">Audio & Video Gen:</span>
              <span className="font-mono font-semibold">
                {modelDefaults?.video?.code || 'gemini-omni-1.1-flash-preview'}
              </span>
            </span>
            <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-2.5 py-1 font-medium text-foreground">
              <Clock size={12} className="text-muted-foreground" />
              <span>
                {tempProjectData?.video_length || '16'}s target ({scenes.length} scenes)
              </span>
            </span>
          </div>

          {!isReadOnly && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mr-1">
                <Globe size={12} /> Language:
              </span>
              {PRODUCTION_LANGUAGES.map((langOpt) => {
                const currentLang: ProductionLanguage =
                  ((tempProjectData as any)?.language as ProductionLanguage) || 'en-IN'
                const isSelected = currentLang === langOpt.id
                return (
                  <Button
                    key={langOpt.id}
                    variant={isSelected ? 'primary' : 'outline'}
                    size="xs"
                    onClick={async () => {
                      if (!productionId || currentLang === langOpt.id) return
                      await api.projects.update(productionId, { language: langOpt.id }).catch(() => {})
                      analyzeCalledRef.current = false
                      setTempProjectData({
                        ...tempProjectData!,
                        language: langOpt.id,
                        scenes: [],
                      } as any)
                    }}
                    title={`Switch audio & narration language to ${langOpt.label} and regenerate script`}
                  >
                    {langOpt.label}
                  </Button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Live Step-by-Step Pipeline & Token/Cost Telemetry Panel */}
      {pipelineSteps.length > 0 && (
        <div className="rounded-xl border border-border bg-card/90 p-4 shadow-sm space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-2.5">
            <div className="flex items-center gap-2">
              <Sparkles size={15} className="text-accent" />
              <h3 className="text-sm font-heading font-bold text-foreground">
                Production Pipeline & Live Token Telemetry
              </h3>
              {production?.pipeline_stage && (
                <span className="px-2 py-0.5 rounded bg-muted text-[10px] font-mono uppercase tracking-wider text-muted-foreground border border-border">
                  Stage: {production.pipeline_stage}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="text-muted-foreground">Cumulative Cost:</span>
              <span className="font-bold text-accent-dark">${estimatedCost.toFixed(4)}</span>
            </div>
          </div>

          <div className="divide-y divide-border/40">
            {pipelineSteps.map((step) => (
              <div
                key={step.step_id}
                className="py-2.5 flex flex-col md:flex-row md:items-center justify-between gap-2"
              >
                <div className="flex items-start md:items-center gap-2.5">
                  <StepStatusIcon status={step.status} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-foreground">{step.label}</span>
                      <span className="text-[10px] uppercase font-mono text-muted-foreground">
                        [{step.status}]
                      </span>
                    </div>
                    {step.detail && (
                      <p className="text-[11px] text-muted-foreground">{step.detail}</p>
                    )}
                  </div>
                </div>
                <StepUsageBadges usage={step.usage} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Continuity Review & Video Evaluation Summary Drawer/Cards */}
      {(reviewReport || evalReport) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {reviewReport && (
            <div className="rounded-xl border border-border bg-card/85 p-4 shadow-sm space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Wand2 size={15} className="text-accent" />
                  <span className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
                    Storyboard Continuity Review
                  </span>
                  <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-500 border border-emerald-500/20 text-[10px] font-mono font-bold">
                    Score: {reviewReport.overall_score}/100
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowReviewDetails(!showReviewDetails)}
                >
                  {showReviewDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  <span className="ml-1 text-[11px]">
                    {showReviewDetails ? 'Hide' : `Issues (${reviewReport.issues?.length || 0})`}
                  </span>
                </Button>
              </div>

              <p className="text-xs text-muted-foreground leading-relaxed">{reviewReport.summary}</p>
              <StepUsageBadges usage={reviewReport.usage} />

              {showReviewDetails && reviewReport.issues && reviewReport.issues.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-border/50 max-h-60 overflow-y-auto">
                  {reviewReport.issues.map((issue, idx) => (
                    <div
                      key={idx}
                      className="rounded-lg bg-muted/40 border border-border/60 p-2.5 text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-bold text-[10px] uppercase text-accent-dark">
                          Scene {issue.scene_number} • {issue.category}
                        </span>
                        <span
                          className={cn(
                            'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase',
                            issue.severity === 'critical'
                              ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                              : 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
                          )}
                        >
                          {issue.severity}
                        </span>
                      </div>
                      <p className="text-muted-foreground">
                        <strong className="text-foreground">Problem:</strong> {issue.problem}
                      </p>
                      <p className="text-emerald-400/90">
                        <strong>Fix Applied:</strong> {issue.fix_applied}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {evalReport && (
            <div className="rounded-xl border border-border bg-card/85 p-4 shadow-sm space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <ShieldCheck size={15} className="text-emerald-500" />
                  <span className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
                    Finished-Video AI Evaluation
                  </span>
                  <span
                    className={cn(
                      'px-2 py-0.5 rounded text-[10px] font-mono font-bold border',
                      evalReport.passed
                        ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-500 border-amber-500/20',
                    )}
                  >
                    Score: {evalReport.overall_score}/100 ({evalReport.passed ? 'Passed' : 'Needs Regeneration'})
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  {canWrite && !isRendering && (
                    <>
                      <Button
                        variant="outline"
                        size="xs"
                        icon={isEvaluatingVideo ? Loader2 : RefreshCw}
                        onClick={handleEvaluateVideo}
                        disabled={isEvaluatingVideo}
                      >
                        {isEvaluatingVideo ? 'Evaluating...' : 'Re-run Eval'}
                      </Button>
                      {!evalReport.passed && (
                        <Button
                          variant="primary"
                          size="xs"
                          icon={isRegeneratingFlagged ? Loader2 : Sparkles}
                          onClick={handleRegenerateFlagged}
                          disabled={isRegeneratingFlagged}
                        >
                          {isRegeneratingFlagged ? 'Regenerating...' : 'Regenerate Flagged'}
                        </Button>
                      )}
                    </>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowEvalDetails(!showEvalDetails)}
                  >
                    {showEvalDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    <span className="ml-1 text-[11px]">
                      {showEvalDetails ? 'Hide' : `Findings (${evalReport.findings?.length || 0})`}
                    </span>
                  </Button>
                </div>
              </div>

              <p className="text-xs text-muted-foreground leading-relaxed">{evalReport.summary}</p>
              <StepUsageBadges usage={evalReport.usage} />

              {showEvalDetails && evalReport.findings && evalReport.findings.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-border/50 max-h-60 overflow-y-auto">
                  {evalReport.findings.map((finding, idx) => (
                    <div
                      key={idx}
                      className="rounded-lg bg-muted/40 border border-border/60 p-2.5 text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-bold text-[10px] uppercase text-accent-dark">
                          Scene {finding.scene_number} • {finding.category}
                        </span>
                        <div className="flex items-center gap-1.5">
                          {finding.regenerate_frame && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[9px] font-mono">
                              Regen Frame
                            </span>
                          )}
                          {finding.regenerate_video && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[9px] font-mono">
                              Regen Video
                            </span>
                          )}
                          <EvalStatusPill status={finding.severity} />
                        </div>
                      </div>
                      <p className="text-muted-foreground">{finding.observed_issue}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className={cn(
        "grid gap-6 transition-all duration-500",
        layout === 'grid' ? "grid-cols-1 md:grid-cols-2 lg:grid-cols-3" : "grid-cols-1"
      )}>
        <AnimatePresence mode="popLayout">
          {scenes.map((scene, index) => (
            <motion.div
              key={scene.id}
              layout
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.2, delay: index * 0.05 }}
              className="space-y-0"
            >
              <SceneMetaBanner
                scene={scene}
                index={index}
                compact={layout === 'grid'}
              />
              <SceneItem
                scene={scene}
                index={index}
                layout={layout}
                isReadOnly={isReadOnly}
                productionId={productionId}
                orientation={(tempProjectData as any)?.orientation || '16:9'}
                onUpdate={(updates) => updateScene(scene.id, updates)}
              />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {!isReadOnly && (
        <div className="flex justify-center pt-4">
          <Button variant="secondary" icon={Plus} onClick={addScene}>Add New Scene</Button>
        </div>
      )}

      <motion.div
        initial={{ y: 100 }}
        animate={{ y: 0 }}
        className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50"
      >
        <CostBreakdownPill
          inputTokens={inputTokens}
          outputTokens={outputTokens}
          totalCost={estimatedCost}
          veoVideos={veoVideos}
          veoSeconds={veoSeconds}
          veoUnitCost={veoUnitCost}
          veoCost={veoCost}
          className="glass bg-card/90 shadow-2xl rounded-full border-accent/20 [&>button]:px-4 [&>button]:py-2.5 [&>button]:text-xs"
        />
      </motion.div>
    </motion.div>
  )
}
