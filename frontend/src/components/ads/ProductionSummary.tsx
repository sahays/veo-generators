import { motion } from 'framer-motion'
import { ArrowLeft, Play, FileText, LayoutGrid, Cpu, CheckCircle2, Plus } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import type { Scene } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { useEffect } from 'react'

export const ProductionSummary = () => {
  const { tempProjectData, setTempProjectData, setActiveProject, projects } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  useEffect(() => {
    if (id) {
      const project = projects.find(p => p.id === id)
      if (project) {
        setActiveProject(id)
      }
    }
  }, [id, projects, setActiveProject])

  const handleStartFresh = () => {
    setActiveProject(null)
    setTempProjectData(null)
    navigate('/productions/new')
  }

  if (!tempProjectData) return null

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
          <div className="aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl relative group border border-white/5">
            <div className="absolute inset-0 flex items-center justify-center bg-accent/5">
              <div className="w-20 h-20 rounded-full bg-accent/20 backdrop-blur-md flex items-center justify-center border border-accent/30 group-hover:scale-110 transition-transform cursor-pointer">
                <Play className="text-accent-dark fill-accent-dark ml-1" size={32} />
              </div>
            </div>
            <div className="absolute bottom-6 left-6 right-6 flex items-center justify-between opacity-0 group-hover:opacity-100 transition-opacity">
               <div className="h-1 flex-1 bg-white/20 rounded-full mr-4 overflow-hidden">
                  <div className="h-full w-1/3 bg-accent" />
               </div>
               <span className="text-[10px] font-mono text-white">00:08 / 00:24</span>
            </div>
          </div>

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
                <p className="text-sm font-medium">{tempProjectData.scenes?.length || 0} segments</p>
              </div>
            </div>
          </Card>
        </div>

        {/* Sidebar: Metadata & Metrics */}
        <div className="space-y-6">
          <Card title="Resource Usage" icon={Cpu}>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Total Tokens</span>
                <span className="text-sm font-mono font-bold">2,450</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Production Cost</span>
                <span className="text-sm font-mono font-bold text-accent-dark">$0.042</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Compute Time</span>
                <span className="text-sm font-mono font-bold">1m 12s</span>
              </div>
            </div>
          </Card>

          <Card title="Technical Specs" icon={LayoutGrid}>
             <div className="space-y-3">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-muted-foreground">Resolution</span>
                  <span className="font-medium">1080x1920 (9:16)</span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <span className="text-muted-foreground">FPS</span>
                  <span className="font-medium">30 fps</span>
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
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <LayoutGrid size={18} className="text-accent-dark" />
          <h3 className="text-lg font-heading font-bold">Final Storyboard</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {tempProjectData.scenes?.map((scene: Scene, i: number) => (
            <div key={scene.id} className="glass rounded-xl overflow-hidden group border border-border/40">
              <div className="aspect-video relative">
                <img src={scene.thumbnail_url} className="w-full h-full object-cover" />
                <div className="absolute top-2 left-2 bg-black/60 backdrop-blur-sm px-1.5 py-0.5 rounded text-[8px] font-mono text-white">
                  {scene.timestamp_start}
                </div>
              </div>
              <div className="p-2.5">
                <p className="text-[10px] text-muted-foreground line-clamp-2">Scene {i + 1}: {scene.visual_description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  )
}
