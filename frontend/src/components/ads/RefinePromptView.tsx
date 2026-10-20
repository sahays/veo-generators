import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, Sparkles, AlertCircle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/Common'
import { Skeleton } from '@/components/ui/skeleton'
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

const RefineLoadingState = () => (
  <div className="w-full space-y-5 pb-20" aria-busy="true" aria-label="Loading production studio">
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-2">
        <Skeleton className="h-6 w-64 rounded-md" />
        <Skeleton className="h-3 w-96 max-w-full rounded-md" />
        <Skeleton className="h-1.5 w-52 rounded-full" />
      </div>
      <Skeleton className="h-8 w-40 rounded-md" />
    </div>
    <Skeleton className="h-9 w-48 rounded-xl" />
    <div className="space-y-px overflow-hidden rounded-2xl">
      {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-16 w-full rounded-none" />)}
    </div>
  </div>
)

function snapshotPanelProps(snap: Project | null, d?: Partial<Project> | null) {
  return {
    storyGraph: snap?.story_graph || d?.story_graph,
    currentStage: snap?.current_stage || d?.current_stage,
    pipelineStatus: snap?.status || d?.status,
    pipelineError: snap?.error_message || d?.error_message,
    blockedGate: snap?.blocked_gate ?? d?.blocked_gate,
    finalVideoUrl: snap?.final_video_url || d?.final_video_url,
    renderQuality: snap?.render_quality || d?.render_quality,
    videoResolution: snap?.video_resolution || d?.video_resolution,
  }
}

function buildStudioMeta(d?: Partial<Project> | null): string[] {
  const lang = PRODUCTION_LANGUAGES.find((l) => l.id === (d?.language || 'en-IN'))?.label || d?.language || 'en-IN'
  return [d?.orientation || '16:9', `${d?.video_length || '16'}s`, lang]
}

const StudioUsage = ({ d }: { d?: Partial<Project> | null }) => (
  <CostBreakdownPill
    inputTokens={d?.total_usage?.input_tokens || 0}
    outputTokens={d?.total_usage?.output_tokens || 0}
    totalCost={d?.total_usage?.cost_usd || 0}
    imageGenerations={d?.total_usage?.image_generations || 0}
    imageCost={d?.total_usage?.image_cost_usd || 0}
    veoVideos={d?.total_usage?.veo_videos || 0}
    veoSeconds={d?.total_usage?.veo_seconds || 0}
    veoUnitCost={d?.total_usage?.veo_unit_cost || 0}
    veoCost={d?.total_usage?.veo_cost_usd || 0}
  />
)

function useStoryGraphBootstrap(productionId: string) {
  const { tempProjectData, setActiveProject, setTempProjectData } = useProjectStore()
  const { projects: projectsApi } = useAdsProjectActions()
  const [isLoadingGraph, setIsLoadingGraph] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [storyGraphSnap, setStoryGraphSnap] = useState<Project | null>(null)

  useEffect(() => {
    if (!productionId) return
    let cancelled = false
    const sync = (snap: Project) => {
      setStoryGraphSnap(snap)
      setTempProjectData({ ...(tempProjectData || {}), ...snap, scenes: snap.scenes || [] })
      setActiveProject(productionId)
    }
    setIsLoadingGraph(true)
    setLoadError(null)
    projectsApi
      .getStoryGraph(productionId)
      .then((snap) => {
        if (cancelled || !snap?.id) return
        sync(snap)
      })
      .catch((err) => !cancelled && setLoadError(`Failed to load StoryGraph studio: ${err instanceof Error ? err.message : String(err)}`))
      .finally(() => !cancelled && setIsLoadingGraph(false))
    return () => {
      cancelled = true
    }
  }, [productionId, projectsApi, setActiveProject, setTempProjectData])

  return { isLoadingGraph, loadError, storyGraphSnap, setStoryGraphSnap }
}

export const RefinePromptView = () => {
  const { tempProjectData, setTempProjectData } = useProjectStore()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const productionId = id || tempProjectData?.id || ''
  const boot = useStoryGraphBootstrap(productionId)

  if (boot.loadError) return <RefineErrorState loadError={boot.loadError} id={id} onNavigate={navigate} />
  if (boot.isLoadingGraph) return <RefineLoadingState />
  const activeData = boot.storyGraphSnap || (tempProjectData as Partial<Project> | null)

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} className="w-full pb-20">
      {productionId && (
        <StoryGraphStudioPanel
          productionId={productionId} {...snapshotPanelProps(boot.storyGraphSnap, activeData)}
          canWrite={canWrite}
          title={activeData?.name || 'Production studio'}
          subtitle={activeData?.base_concept}
          meta={buildStudioMeta(activeData)}
          usage={<StudioUsage d={activeData} />}
          onBack={() => navigate('/productions')}
          onEditBrief={id ? () => navigate(`/productions/${id}/edit`) : undefined}
          onGraphUpdated={(snap) => { boot.setStoryGraphSnap(snap); setTempProjectData({ ...(tempProjectData || {}), ...snap, scenes: snap?.scenes || [] }) }}
        />
      )}
    </motion.div>
  )
}
