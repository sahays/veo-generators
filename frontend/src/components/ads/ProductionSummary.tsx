import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { PromptModal } from '@/components/ads/PromptModal'
import { useProjectStore } from '@/store/useProjectStore'
import { useAuthStore } from '@/store/useAuthStore'
import type { Project, Scene } from '@/types/project'
import { useAdsProjectActions } from './projects/useAdsProjectActions'
import {
  ProductionSummaryHeader,
  ProductionVideoAndBrief,
  ProductionMetricsSidebar,
  FinalStoryboardGrid,
} from './studio/ProductionSummarySections'

function useProductionSummaryController(id: string | undefined) {
  const { tempProjectData, setTempProjectData, setActiveProject } = useProjectStore()
  const { projects: projectsApi } = useAdsProjectActions()
  const navigate = useNavigate()
  const [isLoading, setIsLoading] = useState(false)
  const [isUpgrading, setIsUpgrading] = useState(false)

  useEffect(() => {
    if (!id) return
    setIsLoading(true)
    projectsApi.get(id).then((project: Project) => {
      if (project?.id) { setTempProjectData({ ...project, scenes: project.scenes || [] }); setActiveProject(id) }
    }).catch(() => null).finally(() => setIsLoading(false))
  }, [id, projectsApi, setActiveProject, setTempProjectData])

  const handleUpgradeToFinal = async () => {
    const prodId = tempProjectData?.id || id
    if (!prodId) return
    setIsUpgrading(true)
    try {
      await projectsApi.render(prodId, { quality: 'final', resolution: '720p', auto_review: false, auto_eval: true })
      const updated = await projectsApi.get(prodId).catch(() => null)
      if (updated) setTempProjectData({ ...updated, scenes: updated.scenes || [] })
      navigate(`/productions/${prodId}/script`)
    } finally {
      setIsUpgrading(false)
    }
  }

  return { tempProjectData, isLoading, isUpgrading, handleUpgradeToFinal, handleStartFresh: () => { setActiveProject(null); setTempProjectData(null); navigate('/productions/new') } }
}

const ProductionSummaryView = ({
  id, project, canWrite, isUpgrading, modelConfig, setModelConfig, selectedScene, setSelectedScene,
  showAnalysisPrompt, setShowAnalysisPrompt, onUpgradeToFinal, onStartFresh, onNavigate,
}: {
  id?: string; project: Project; canWrite: boolean; isUpgrading: boolean
  modelConfig: { modelId?: string; region?: string }; setModelConfig: (val: { modelId?: string; region?: string }) => void
  selectedScene: Scene | null; setSelectedScene: (s: Scene | null) => void
  showAnalysisPrompt: boolean; setShowAnalysisPrompt: (v: boolean) => void
  onUpgradeToFinal: () => void; onStartFresh: () => void; onNavigate: (path: string) => void
}) => (
  <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: -0.98 }} className="w-full space-y-6 pb-20">
    <ProductionSummaryHeader
      project={project} canWrite={canWrite} isUpgrading={isUpgrading} modelConfig={modelConfig} onModelConfigChange={setModelConfig}
      onUpgradeToFinal={onUpgradeToFinal} onOpenStudio={() => onNavigate(`/productions/${id}/script`)} onStartFresh={onStartFresh} onBack={() => onNavigate('/productions')}
    />
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <ProductionVideoAndBrief project={project} scenes={project.scenes || []} showAnalysisPrompt={showAnalysisPrompt} onToggleAnalysisPrompt={() => setShowAnalysisPrompt(!showAnalysisPrompt)} />
      <ProductionMetricsSidebar id={id} project={project} scenesCount={(project.scenes || []).length} />
    </div>
    {(project.scenes || []).length > 0 && (
      <FinalStoryboardGrid scenes={project.scenes || []} aspectClass={project.orientation === '9:16' ? 'aspect-[9/16]' : 'aspect-video'} onSelectScene={setSelectedScene} />
    )}
    {selectedScene && (
      <PromptModal scene={selectedScene} productionId={id || ''} isReadOnly onClose={() => setSelectedScene(null)} onGenerateFrame={async () => {}} onGenerateVideo={async () => {}} onDescriptionChange={() => {}} />
    )}
  </motion.div>
)

export const ProductionSummary = () => {
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [showAnalysisPrompt, setShowAnalysisPrompt] = useState(false)
  const ctrl = useProductionSummaryController(id)

  if (ctrl.isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading production...</p>
      </div>
    )
  }
  if (!ctrl.tempProjectData) return null

  return (
    <ProductionSummaryView
      id={id} project={ctrl.tempProjectData as unknown as Project} canWrite={canWrite} isUpgrading={ctrl.isUpgrading}
      modelConfig={modelConfig} setModelConfig={setModelConfig} selectedScene={selectedScene} setSelectedScene={setSelectedScene}
      showAnalysisPrompt={showAnalysisPrompt} setShowAnalysisPrompt={setShowAnalysisPrompt}
      onUpgradeToFinal={ctrl.handleUpgradeToFinal} onStartFresh={ctrl.handleStartFresh} onNavigate={navigate}
    />
  )
}
