import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Sparkles, Video, Play, ImageIcon,
  RotateCcw, Clock, DollarSign, Cpu, Save,
  Loader2, LayoutGrid, List, Plus, Lock, AlertCircle
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import type { Scene } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

export const RefinePromptView = () => {
  const { tempProjectData, updateScene, addScene, setActiveProject, setTempProjectData } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [layout, setLayout] = useState<'grid' | 'list'>('list')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [activeAction, setActiveAction] = useState<'storyboard' | 'video' | null>(null)
  const analyzeCalledRef = useRef(false)

  // On mount: load production from API if we don't have tempProjectData
  useEffect(() => {
    if (id && !tempProjectData) {
      api.projects.get(id).then((p) => {
        if (p && p.id) {
          setTempProjectData({ ...p, scenes: p.scenes || [] })
          setActiveProject(id)
        }
      }).catch(() => {
        setAnalysisError('Failed to load production')
      })
    }
  }, [id, tempProjectData, setActiveProject, setTempProjectData])

  const isReadOnly = (tempProjectData as any)?.status === 'completed'
  const scenes = tempProjectData?.scenes || []

  // Call real Gemini analysis if no scenes exist
  useEffect(() => {
    if (scenes.length > 0 || isAnalyzing || isReadOnly || !tempProjectData || analyzeCalledRef.current) return

    const productionId = (tempProjectData as any)?.id || id
    if (!productionId) return

    analyzeCalledRef.current = true
    setIsAnalyzing(true)
    setAnalysisError(null)

    const promptId = tempProjectData.prompt_id

    api.projects.analyze(productionId, promptId)
      .then((result) => {
        // The analyze endpoint returns AIResponseWrapper: { data: Scene[], usage: UsageMetrics }
        const newScenes: Scene[] = (result.data || []).map((s: any, i: number) => ({
          id: s.id || `s-${i}`,
          visual_description: s.visual_description,
          timestamp_start: s.timestamp_start,
          timestamp_end: s.timestamp_end,
          metadata: s.metadata || {},
          thumbnail_url: s.thumbnail_url,
          tokens_consumed: s.usage ? { input: s.usage.input_tokens || 0, output: s.usage.output_tokens || 0 } : undefined,
        }))
        setTempProjectData({ ...tempProjectData, scenes: newScenes })
        setIsAnalyzing(false)
      })
      .catch((err) => {
        console.error('Analysis failed:', err)
        setAnalysisError('Gemini analysis failed. Please try again.')
        setIsAnalyzing(false)
      })
  }, [scenes.length, isAnalyzing, isReadOnly, tempProjectData, id, setTempProjectData])

  const onGenerate = (type: 'storyboard' | 'video') => {
    setActiveAction(type)
    setTimeout(() => {
      setActiveAction(null)
      navigate('/productions')
    }, 2500)
  }

  const totalTokens = scenes.reduce((acc, s) => acc + (s.tokens_consumed?.input || 0) + (s.tokens_consumed?.output || 0), 0)
  const estimatedCost = (totalTokens / 1000) * 0.015

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
      className="max-w-6xl mx-auto space-y-8 pb-32"
    >
      <div className="flex items-center justify-between py-4 border-b border-border">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate(isReadOnly ? `/productions/${id}` : (id ? `/productions/${id}/edit` : '/productions/new'))} 
            className="p-2 hover:bg-muted rounded-xl transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-heading text-foreground tracking-tight">Script Editor</h2>
              {isReadOnly && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-muted-foreground text-[9px] font-bold uppercase tracking-wider border border-border">
                  <Lock size={10} /> Read Only
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">Fine-tune each scene before final production.</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center bg-muted/50 p-1 rounded-lg border border-border mr-2">
            <button 
              onClick={() => setLayout('list')}
              className={cn(
                "p-1.5 rounded-md transition-all",
                layout === 'list' ? "bg-accent text-slate-900 shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <List size={16} />
            </button>
            <button 
              onClick={() => setLayout('grid')}
              className={cn(
                "p-1.5 rounded-md transition-all",
                layout === 'grid' ? "bg-accent text-slate-900 shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <LayoutGrid size={16} />
            </button>
          </div>

          <div className="hidden md:flex flex-col items-end px-4 border-r border-border">
            <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-widest">Est. Cost</span>
            <span className="text-sm font-mono font-bold text-accent-dark">${estimatedCost.toFixed(3)}</span>
          </div>
          
          {!isReadOnly && (
            <Button icon={Play} onClick={() => onGenerate('video')} disabled={!!activeAction}>
              {activeAction === 'video' ? 'Generating...' : 'Generate Video'}
            </Button>
          )}
        </div>
      </div>

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
            >
              <SceneItem 
                scene={scene} 
                index={index} 
                layout={layout} 
                isReadOnly={isReadOnly}
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
        className="fixed bottom-6 left-1/2 -translate-x-1/2 glass bg-card/90 px-6 py-3 rounded-full shadow-2xl flex items-center gap-8 z-50 border-accent/20"
      >
        <div className="flex items-center gap-2">
          <Cpu className="text-accent-dark" size={16} />
          <div className="flex flex-col">
            <span className="text-[9px] uppercase font-bold text-muted-foreground leading-none">Usage</span>
            <span className="text-xs font-mono font-bold">{totalTokens.toLocaleString()} tokens</span>
          </div>
        </div>
        <div className="w-px h-6 bg-border" />
        <div className="flex items-center gap-2">
          <DollarSign className="text-accent-dark" size={16} />
          <div className="flex flex-col">
            <span className="text-[9px] uppercase font-bold text-muted-foreground leading-none">Cost</span>
            <span className="text-xs font-mono font-bold">${estimatedCost.toFixed(3)}</span>
          </div>
        </div>
      </motion.div>
    </motion.div>
  )
}

const SceneItem = ({ 
  scene, 
  index, 
  layout, 
  isReadOnly,
  onUpdate 
}: { 
  scene: Scene, 
  index: number, 
  layout: 'grid' | 'list',
  isReadOnly: boolean,
  onUpdate: (updates: Partial<Scene>) => void
}) => {
  const [isGeneratingFrame, setIsGeneratingFrame] = useState(false)

  if (layout === 'grid') {
    return (
      <Card className="p-0 overflow-hidden group border-border/40 hover:border-accent/50 transition-all">
        <div className="relative aspect-video overflow-hidden">
          {isGeneratingFrame ? (
            <div className="w-full h-full bg-muted flex items-center justify-center">
              <Loader2 className="animate-spin text-accent" size={24} />
            </div>
          ) : scene.thumbnail_url ? (
            <img
              src={scene.thumbnail_url}
              className="w-full h-full object-cover transition-all duration-700 group-hover:scale-105"
            />
          ) : (
            <div className="w-full h-full bg-muted flex items-center justify-center">
              <ImageIcon size={32} className="text-muted-foreground/20" />
            </div>
          )}
          
          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity p-4 flex flex-col justify-end gap-2">
             <div className="flex flex-wrap gap-1">
                {Object.values(scene.metadata || {}).slice(0, 3).map((v, i) => (
                  <span key={i} className="text-[8px] font-bold uppercase bg-white/20 backdrop-blur-md px-1.5 py-0.5 rounded text-white border border-white/10">
                    {v}
                  </span>
                ))}
             </div>
          </div>

          <div className="absolute top-3 left-3 bg-black/60 backdrop-blur-md px-2 py-1 rounded text-[10px] font-mono text-white border border-white/10">
            {scene.timestamp_start}
          </div>
        </div>

        <div className="p-4 space-y-3 bg-card/50">
          <textarea
            value={scene.visual_description}
            onChange={(e) => onUpdate({ visual_description: e.target.value })}
            readOnly={isReadOnly}
            className={cn(
              "w-full text-xs leading-relaxed bg-transparent border-none focus:ring-0 outline-none resize-none p-0 min-h-[60px]",
              isReadOnly && "cursor-default"
            )}
            placeholder="Scene description..."
          />
          <div className="flex items-center justify-between pt-2 border-t border-border/50">
            <span className="text-[10px] font-bold uppercase text-muted-foreground">Scene {index + 1}</span>
            {!isReadOnly && (
              <div className="flex gap-2">
                <button onClick={() => setIsGeneratingFrame(true)} className="p-1.5 hover:bg-accent/10 rounded-md text-accent-dark transition-colors">
                  <RotateCcw size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card 
      title={`Scene ${index + 1}: ${scene.timestamp_start} - ${scene.timestamp_end}`}
      className="p-4 overflow-hidden group transition-all duration-300"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className={cn(
          "space-y-4",
          layout === 'list' ? "lg:col-span-8" : ""
        )}>
          <textarea
            value={scene.visual_description}
            onChange={(e) => onUpdate({ visual_description: e.target.value })}
            readOnly={isReadOnly}
            className={cn(
              "w-full min-h-[100px] p-3 rounded-xl text-sm leading-relaxed bg-muted/30 border border-border focus:ring-2 focus:ring-accent/30 outline-none resize-none transition-all",
              isReadOnly && "cursor-default bg-transparent"
            )}
            placeholder="Scene visual description..."
          />
          
          <div className="flex flex-wrap gap-2">
            {Object.entries(scene.metadata || {}).map(([key, value]) => (
              <div key={key} className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-accent/10 border border-accent/20 text-[9px] font-bold uppercase tracking-wider text-accent-dark">
                <span className="opacity-60">{key}:</span>
                <span>{value}</span>
              </div>
            ))}
          </div>

          {!isReadOnly && (
            <div className="flex items-center gap-3">
              <Button variant="ghost" className="h-7 px-2.5 text-[10px]" icon={RotateCcw}>Regenerate</Button>
              <Button 
                variant="secondary" 
                className="h-7 px-2.5 text-[10px]" 
                icon={ImageIcon}
                onClick={() => setIsGeneratingFrame(true)}
              >
                Update Frame
              </Button>
            </div>
          )}
        </div>

        <div className="relative lg:col-span-4 aspect-video rounded-xl bg-muted/50 border border-dashed border-border flex items-center justify-center overflow-hidden">
          {isGeneratingFrame ? (
            <div className="absolute inset-0 bg-muted flex items-center justify-center">
              <div className="flex flex-col items-center gap-1">
                <Loader2 className="animate-spin text-accent" size={20} />
                <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-widest">Generating...</span>
              </div>
            </div>
          ) : scene.thumbnail_url ? (
            <img
              src={scene.thumbnail_url}
              className="w-full h-full object-cover transition-all duration-500"
            />
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <ImageIcon size={24} strokeWidth={1.5} />
              <span className="text-[9px] font-bold uppercase tracking-widest">No frame yet</span>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}
