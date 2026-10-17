import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Sparkles,
  Lock,
  AlertCircle,
  Globe,
  Clock,
  Monitor,
  Smartphone,
  GitBranch,
  Sliders,
} from 'lucide-react'
import { Button } from '@/components/Common'
import { CostBreakdownPill } from '@/components/ads/CostBreakdownPill'
import { StoryGraphStudioPanel } from '@/components/ads/StoryGraphStudioPanel'
import { useProjectStore } from '@/store/useProjectStore'
import { useAuthStore } from '@/store/useAuthStore'
import { PRODUCTION_LANGUAGES } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

export const RefinePromptView = () => {
  const { tempProjectData, setActiveProject, setTempProjectData } = useProjectStore()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [isLoadingGraph, setIsLoadingGraph] = useState(true)
  const [isAutoStarting, setIsAutoStarting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [storyGraphSnap, setStoryGraphSnap] = useState<any>(null)
  const autoStartTriggeredRef = useRef(false)

  const productionId = id || (tempProjectData as any)?.id || ''

  useEffect(() => {
    if (!productionId) return
    let cancelled = false
    setIsLoadingGraph(true)
    setLoadError(null)

    api.projects
      .getStoryGraph(productionId)
      .then(async (snap) => {
        if (cancelled) return
        if (snap && snap.id) {
          setStoryGraphSnap(snap)
          setTempProjectData({
            ...(tempProjectData || {}),
            ...snap,
            scenes: snap.scenes || [],
          } as any)
          setActiveProject(productionId)

          const completedStages = (snap.story_graph?.stage_runs || []).filter(
            (sr: any) => sr.completed,
          )
          const hasExtractedEntities =
            (snap.story_graph?.entities?.all || []).length > 0

          if (
            canWrite &&
            !autoStartTriggeredRef.current &&
            !hasExtractedEntities &&
            completedStages.length <= 1
          ) {
            autoStartTriggeredRef.current = true
            setIsAutoStarting(true)
            try {
              const started = await api.projects.runStoryGraph(productionId, {
                auto_approve_gates: snap.auto_approve_gates ?? false,
              })
              if (!cancelled && started && started.id) {
                setStoryGraphSnap(started)
                setTempProjectData({
                  ...(tempProjectData || {}),
                  ...started,
                  scenes: started.scenes || [],
                } as any)
              }
            } catch (runErr) {
              console.error('Initial StoryGraph run failed:', runErr)
            } finally {
              if (!cancelled) setIsAutoStarting(false)
            }
          }
        }
      })
      .catch((err) => {
        if (cancelled) return
        const detail = err instanceof Error ? err.message : String(err)
        setLoadError(`Failed to load StoryGraph studio: ${detail}`)
      })
      .finally(() => {
        if (!cancelled) setIsLoadingGraph(false)
      })

    return () => {
      cancelled = true
    }
  }, [productionId, canWrite])

  const activeData = storyGraphSnap || (tempProjectData as any)
  const totalUsage = activeData?.total_usage
  const inputTokens = totalUsage?.input_tokens || 0
  const outputTokens = totalUsage?.output_tokens || 0
  const estimatedCost = totalUsage?.cost_usd || 0
  const imageGenerations = totalUsage?.image_generations || 0
  const imageCost = totalUsage?.image_cost_usd || 0
  const veoVideos = totalUsage?.veo_videos || 0
  const veoSeconds = totalUsage?.veo_seconds || 0
  const veoUnitCost = totalUsage?.veo_unit_cost || 0
  const veoCost = totalUsage?.veo_cost_usd || 0

  const currentLangId = activeData?.language || 'en-IN'
  const currentLangLabel =
    PRODUCTION_LANGUAGES.find((l) => l.id === currentLangId)?.label || currentLangId
  const orientation = activeData?.orientation || '16:9'
  const videoLength = activeData?.video_length || '16'

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-6">
        <div className="w-20 h-20 rounded-full bg-red-500/10 flex items-center justify-center">
          <AlertCircle className="text-red-500" size={32} />
        </div>
        <div className="text-center space-y-2 max-w-md">
          <h3 className="text-xl font-heading font-bold text-red-500">
            Could Not Load StoryGraph Studio
          </h3>
          <p className="text-sm text-muted-foreground">{loadError}</p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => navigate(id ? `/productions/${id}/edit` : '/productions')}
            icon={ArrowLeft}
          >
            Back to Brief
          </Button>
          <Button
            variant="primary"
            onClick={() => window.location.reload()}
            icon={Sparkles}
          >
            Retry
          </Button>
        </div>
      </div>
    )
  }

  if (isLoadingGraph || isAutoStarting) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-6">
        <div className="relative">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 4, repeat: Infinity, ease: 'linear' }}
            className="w-20 h-20 border-2 border-accent border-t-transparent rounded-full"
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <Sparkles className="text-accent animate-pulse" size={24} />
          </div>
        </div>
        <div className="text-center space-y-2 max-w-md">
          <h3 className="text-xl font-heading font-bold">
            {isAutoStarting
              ? 'Building Story-to-Video Graph (S1: World & Entities)...'
              : 'Loading Story-to-Video Graph Studio...'}
          </h3>
          <p className="text-sm text-muted-foreground">
            {isAutoStarting
              ? 'STORY_ARCHITECT and SCRIPT_SUPERVISOR are extracting canonical Characters, Locations, Objects, Scenes, and StateFact transitions.'
              : 'Fetching your versioned StoryGraph state from Firestore.'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="w-full space-y-5 pb-20"
    >
      {/* Clean Full-Width Studio Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-border">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/productions')}
            title="Back to Productions"
          >
            <ArrowLeft size={20} />
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-heading text-foreground tracking-tight">
                {activeData?.name || 'Story-to-Video Graph Studio'}
              </h2>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-accent/10 text-accent-dark border border-accent/25 text-[10px] font-mono font-bold uppercase">
                <GitBranch size={11} /> StoryGraph v1
              </span>
              {!canWrite && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[9px] font-bold uppercase tracking-wider border border-border">
                  <Lock size={10} /> Read Only
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1 max-w-4xl">
              {activeData?.base_concept ||
                'Multi-agent Story-to-Video Graph pipeline with continuity state tracking, reference budgeting, and deterministic prompt compilation.'}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
            {orientation === '9:16' ? (
              <Smartphone size={12} className="text-accent-dark" />
            ) : (
              <Monitor size={12} className="text-accent-dark" />
            )}
            <span>{orientation}</span>
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
            <Clock size={12} className="text-muted-foreground" />
            <span>{videoLength}s</span>
          </span>
          <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
            <Globe size={12} className="text-muted-foreground" />
            <span>{currentLangLabel}</span>
          </span>

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

          {canWrite && id && (
            <Button
              variant="outline"
              size="xs"
              icon={Sliders}
              onClick={() => navigate(`/productions/${id}/edit`)}
            >
              Edit Brief
            </Button>
          )}
        </div>
      </div>

      {/* Main StoryGraph Studio Workspace */}
      {productionId && (
        <StoryGraphStudioPanel
          productionId={productionId}
          storyGraph={storyGraphSnap?.story_graph || activeData?.story_graph}
          currentStage={storyGraphSnap?.current_stage || activeData?.current_stage}
          pipelineStatus={storyGraphSnap?.status || activeData?.status}
          pipelineError={storyGraphSnap?.error_message || activeData?.error_message}
          blockedGate={storyGraphSnap?.blocked_gate ?? activeData?.blocked_gate}
          finalVideoUrl={storyGraphSnap?.final_video_url || activeData?.final_video_url}
          canWrite={canWrite}
          onGraphUpdated={(snap) => {
            setStoryGraphSnap(snap)
            setTempProjectData({
              ...(tempProjectData || {}),
              ...snap,
              scenes: snap?.scenes || [],
            } as any)
          }}
        />
      )}
    </motion.div>
  )
}

