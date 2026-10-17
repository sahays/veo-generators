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
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/Common'
import { CostBreakdownPill } from '@/components/ads/CostBreakdownPill'
import { StoryGraphStudioPanel } from '@/components/ads/StoryGraphStudioPanel'
import { useProjectStore } from '@/store/useProjectStore'
import { useAuthStore } from '@/store/useAuthStore'
import { PRODUCTION_LANGUAGES, type Project } from '@/types/project'
import { useAdsProjectActions } from './projects/useAdsProjectActions'

const RefineErrorState = ({
  loadError,
  id,
  onNavigate,
}: {
  loadError: string
  id?: string
  onNavigate: (path: string) => void
}) => (
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
        onClick={() => onNavigate(id ? `/productions/${id}/edit` : '/productions')}
        icon={ArrowLeft}
      >
        Back to Brief
      </Button>
      <Button variant="primary" onClick={() => window.location.reload()} icon={Sparkles}>
        Retry
      </Button>
    </div>
  </div>
)

const RefineLoadingState = ({ isAutoStarting }: { isAutoStarting: boolean }) => (
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

const RefineStudioHeader = ({
  activeData,
  canWrite,
  id,
  onNavigate,
}: {
  activeData?: Partial<Project> | null
  canWrite: boolean
  id?: string
  onNavigate: (path: string) => void
}) => (
  <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-border">
    <div className="flex items-center gap-3">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => onNavigate('/productions')}
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
        {(activeData?.orientation || '16:9') === '9:16' ? (
          <Smartphone size={12} className="text-accent-dark" />
        ) : (
          <Monitor size={12} className="text-accent-dark" />
        )}
        <span>{activeData?.orientation || '16:9'}</span>
      </span>
      <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
        <Clock size={12} className="text-muted-foreground" />
        <span>{activeData?.video_length || '16'}s</span>
      </span>
      <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground">
        <Globe size={12} className="text-muted-foreground" />
        <span>
          {PRODUCTION_LANGUAGES.find((l) => l.id === (activeData?.language || 'en-IN'))?.label ||
            activeData?.language ||
            'en-IN'}
        </span>
      </span>

      <CostBreakdownPill
        inputTokens={activeData?.total_usage?.input_tokens || 0}
        outputTokens={activeData?.total_usage?.output_tokens || 0}
        totalCost={activeData?.total_usage?.cost_usd || 0}
        imageGenerations={activeData?.total_usage?.image_generations || 0}
        imageCost={activeData?.total_usage?.image_cost_usd || 0}
        veoVideos={activeData?.total_usage?.veo_videos || 0}
        veoSeconds={activeData?.total_usage?.veo_seconds || 0}
        veoUnitCost={activeData?.total_usage?.veo_unit_cost || 0}
        veoCost={activeData?.total_usage?.veo_cost_usd || 0}
      />

      {canWrite && id && (
        <Button
          variant="outline"
          size="xs"
          icon={Sliders}
          onClick={() => onNavigate(`/productions/${id}/edit`)}
        >
          Edit Brief
        </Button>
      )}
    </div>
  </div>
)

function shouldAutoStartGraph(snap: Project, canWrite: boolean, triggered: boolean): boolean {
  const completed = (snap.story_graph?.stage_runs || []).filter((sr) => sr.completed)
  const hasEntities = (snap.story_graph?.entities?.all || []).length > 0
  return canWrite && !triggered && !hasEntities && completed.length <= 1
}

function useStoryGraphBootstrap(productionId: string, canWrite: boolean) {
  const { tempProjectData, setActiveProject, setTempProjectData } = useProjectStore()
  const { projects: projectsApi } = useAdsProjectActions()
  const [isLoadingGraph, setIsLoadingGraph] = useState(true)
  const [isAutoStarting, setIsAutoStarting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [storyGraphSnap, setStoryGraphSnap] = useState<Project | null>(null)
  const autoStartRef = useRef(false)

  useEffect(() => {
    if (!productionId) return
    let cancelled = false
    const sync = (snap: Project) => { setStoryGraphSnap(snap); setTempProjectData({ ...(tempProjectData || {}), ...snap, scenes: snap.scenes || [] }); setActiveProject(productionId) }
    setIsLoadingGraph(true); setLoadError(null)
    projectsApi.getStoryGraph(productionId).then(async (snap) => {
      if (cancelled || !snap?.id) return
      sync(snap)
      if (shouldAutoStartGraph(snap, canWrite, autoStartRef.current)) {
        autoStartRef.current = true; setIsAutoStarting(true)
        const started = await projectsApi.runStoryGraph(productionId, { auto_approve_gates: snap.auto_approve_gates ?? false }).catch(() => null)
        if (!cancelled && started?.id) sync(started)
        if (!cancelled) setIsAutoStarting(false)
      }
    }).catch((err) => !cancelled && setLoadError(`Failed to load StoryGraph studio: ${err instanceof Error ? err.message : String(err)}`)).finally(() => !cancelled && setIsLoadingGraph(false))
    return () => { cancelled = true }
  }, [productionId, canWrite, projectsApi, setActiveProject, setTempProjectData])

  return { isLoadingGraph, isAutoStarting, loadError, storyGraphSnap, setStoryGraphSnap }
}

export const RefinePromptView = () => {
  const { tempProjectData, setTempProjectData } = useProjectStore()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const productionId = id || tempProjectData?.id || ''
  const boot = useStoryGraphBootstrap(productionId, canWrite)

  if (boot.loadError) return <RefineErrorState loadError={boot.loadError} id={id} onNavigate={navigate} />
  if (boot.isLoadingGraph || boot.isAutoStarting) return <RefineLoadingState isAutoStarting={boot.isAutoStarting} />
  const activeData = boot.storyGraphSnap || (tempProjectData as Partial<Project> | null)

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} className="w-full space-y-5 pb-20">
      <RefineStudioHeader activeData={activeData} canWrite={canWrite} id={id} onNavigate={navigate} />
      {productionId && (
        <StoryGraphStudioPanel
          productionId={productionId} storyGraph={boot.storyGraphSnap?.story_graph || activeData?.story_graph}
          currentStage={boot.storyGraphSnap?.current_stage || activeData?.current_stage}
          pipelineStatus={boot.storyGraphSnap?.status || activeData?.status}
          pipelineError={boot.storyGraphSnap?.error_message || activeData?.error_message}
          blockedGate={boot.storyGraphSnap?.blocked_gate ?? activeData?.blocked_gate}
          finalVideoUrl={boot.storyGraphSnap?.final_video_url || activeData?.final_video_url}
          canWrite={canWrite}
          onGraphUpdated={(snap) => { boot.setStoryGraphSnap(snap); setTempProjectData({ ...(tempProjectData || {}), ...snap, scenes: snap?.scenes || [] }) }}
        />
      )}
    </motion.div>
  )
}
