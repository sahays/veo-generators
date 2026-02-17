import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, Play, FileText, LayoutGrid, Cpu, CheckCircle2, Plus, Loader2, Eye, ChevronDown } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { PromptModal } from '@/components/ads/PromptModal'
import { useProjectStore } from '@/store/useProjectStore'
import type { Project, Scene } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

export const ProductionSummary = () => {
  const { tempProjectData, setTempProjectData, setActiveProject } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [isLoading, setIsLoading] = useState(false)
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [showAnalysisPrompt, setShowAnalysisPrompt] = useState(false)

  // Fetch from API if we don't have tempProjectData
  useEffect(() => {
    if (!id || tempProjectData) return
    setIsLoading(true)
    api.projects.get(id)
      .then((project: Project) => {
        if (project && project.id) {
          setTempProjectData({ ...project, scenes: project.scenes || [] })
          setActiveProject(id)
        }
      })
      .catch((err) => console.error('Failed to load production', err))
      .finally(() => setIsLoading(false))
  }, [id, tempProjectData, setTempProjectData, setActiveProject])

  const handleStartFresh = () => {
    setActiveProject(null)
    setTempProjectData(null)
    navigate('/productions/new')
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading production...</p>
      </div>
    )
  }

  if (!tempProjectData) return null

  const project = tempProjectData as unknown as Project
  const scenes = tempProjectData.scenes || []
  const totalTokens = scenes.reduce((acc, s) => acc + (s.tokens_consumed?.input || 0) + (s.tokens_consumed?.output || 0), 0)
  const estimatedCost = (totalTokens / 1000) * 0.015

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      className="max-w-5xl mx-auto space-y-8 pb-20"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/productions')}
            className="p-2 hover:bg-muted rounded-xl transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h2 className="text-2xl font-heading text-foreground tracking-tight">{tempProjectData.name}</h2>
            <div className="flex items-center gap-2 mt-1">
              <span className="px-1.5 py-0.5 rounded bg-green-500/10 text-green-500 text-[9px] font-bold uppercase tracking-wider border border-green-500/20 flex items-center gap-1">
                <CheckCircle2 size={10} /> Published
              </span>
              <p className="text-xs text-muted-foreground">Generated on {new Date().toLocaleDateString()}</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="ghost" icon={FileText} onClick={() => navigate(`/productions/${id}/script`)}>View Technical Script</Button>
          <Button icon={Plus} onClick={handleStartFresh}>New Production</Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Hero: Video Player */}
        <div className="lg:col-span-2 space-y-6">
          {project.final_video_url ? (
            <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-white/5">
              <video
                controls
                className="w-full h-full"
                src={project.final_video_url}
                poster={scenes[0]?.thumbnail_url}
              />
            </div>
          ) : (
            <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl relative group border border-white/5">
              <div className="absolute inset-0 flex items-center justify-center bg-accent/5">
                <div className="w-20 h-20 rounded-full bg-accent/20 backdrop-blur-md flex items-center justify-center border border-accent/30">
                  <Play className="text-accent-dark fill-accent-dark ml-1" size={32} />
                </div>
              </div>
              <div className="absolute bottom-6 left-6 right-6 text-center">
                <span className="text-xs text-white/60">Video not yet available</span>
              </div>
            </div>
          )}

          <Card title="Production Brief" icon={FileText}>
            <p className="text-sm leading-relaxed italic">"{tempProjectData.base_concept}"</p>
            <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-border/50">
              <div>
                <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Format</p>
                <p className="text-sm font-medium">{tempProjectData.orientation} {tempProjectData.type}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Duration</p>
                <p className="text-sm font-medium">{tempProjectData.video_length} seconds</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-muted-foreground tracking-widest">Total Scenes</p>
                <p className="text-sm font-medium">{scenes.length} segments</p>
              </div>
            </div>
            {project.analysis_prompt && (
              <div className="mt-6 pt-6 border-t border-border/50">
                <button
                  onClick={() => setShowAnalysisPrompt(!showAnalysisPrompt)}
                  className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  <ChevronDown size={14} className={`transition-transform ${showAnalysisPrompt ? 'rotate-180' : ''}`} />
                  Analysis Prompt
                </button>
                {showAnalysisPrompt && (
                  <pre className="mt-3 text-xs leading-relaxed text-foreground bg-muted/30 rounded-xl p-4 whitespace-pre-wrap break-words max-h-48 overflow-y-auto border border-border">
                    {project.analysis_prompt}
                  </pre>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* Sidebar: Metadata & Metrics */}
        <div className="space-y-6">
          <Card title="Resource Usage" icon={Cpu}>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Total Tokens</span>
                <span className="text-sm font-mono font-bold">{totalTokens.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Production Cost</span>
                <span className="text-sm font-mono font-bold text-accent-dark">${estimatedCost.toFixed(3)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Scenes</span>
                <span className="text-sm font-mono font-bold">{scenes.length}</span>
              </div>
            </div>
          </Card>

          <Card title="Technical Specs" icon={LayoutGrid}>
             <div className="space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-muted-foreground">Orientation</span>
                  <span className="font-medium">{tempProjectData.orientation || '16:9'}</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-muted-foreground">Duration</span>
                  <span className="font-medium">{tempProjectData.video_length}s</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-muted-foreground">AI Models</span>
                  <span className="font-medium">Veo 3, Imagen</span>
                </div>
             </div>
          </Card>
        </div>
      </div>

      {/* Storyboard View */}
      {scenes.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <LayoutGrid size={18} className="text-accent-dark" />
            <h3 className="text-lg font-heading font-bold">Final Storyboard</h3>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {scenes.map((scene: Scene, i: number) => (
              <div key={scene.id} className="glass rounded-xl overflow-hidden group border border-border/40">
                <div className="aspect-video relative">
                  {scene.thumbnail_url ? (
                    <img src={scene.thumbnail_url} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full bg-muted flex items-center justify-center">
                      <LayoutGrid size={16} className="text-muted-foreground/30" />
                    </div>
                  )}
                  <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-1.5 py-0.5 rounded text-[8px] font-mono text-white">
                    {scene.timestamp_start}
                  </div>
                  {(scene.image_prompt || scene.video_prompt) && (
                    <button
                      onClick={() => setSelectedScene(scene)}
                      className="absolute top-2 right-2 p-1 bg-black/60 backdrop-blur-sm rounded text-white/70 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      title="View Prompts"
                    >
                      <Eye size={12} />
                    </button>
                  )}
                </div>
                <div className="p-2.5">
                  <p className="text-[10px] text-muted-foreground line-clamp-2">Scene {i + 1}: {scene.visual_description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {selectedScene && (
        <PromptModal
          scene={selectedScene}
          productionId={id || ''}
          isReadOnly
          onClose={() => setSelectedScene(null)}
          onGenerateFrame={async () => {}}
          onGenerateVideo={async () => {}}
          onDescriptionChange={() => {}}
        />
      )}
    </motion.div>
  )
}
