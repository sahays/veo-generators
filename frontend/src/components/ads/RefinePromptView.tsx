import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, Sparkles, Play,
  RotateCcw, Loader2, LayoutGrid, List, Plus, Lock, AlertCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { CostBreakdownPill } from '@/components/ads/CostBreakdownPill'
import { ErrorBadge } from '@/components/ads/ErrorBadge'
import { SceneItem } from '@/components/ads/SceneItem'
import { useProjectStore } from '@/store/useProjectStore'
import { useAuthStore } from '@/store/useAuthStore'

import type { Scene } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '@/lib/api'

export const RefinePromptView = () => {
  const { tempProjectData, updateScene, addScene, setActiveProject, setTempProjectData } = useProjectStore()
  const { isMaster } = useAuthStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [layout, setLayout] = useState<'grid' | 'list'>('list')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [isStartingRender, setIsStartingRender] = useState(false)
  const analyzeCalledRef = useRef(false)

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

  const isGenerating = ['generating', 'stitching'].includes((tempProjectData as any)?.status)
  const isReadOnly = isGenerating || !isMaster
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
        // The analyze endpoint returns AIResponseWrapper: { data: { scenes: [...], ... }, usage: UsageMetrics }
        const scenesData = Array.isArray(result.data) ? result.data : (result.data?.scenes || [])
        const newScenes: Scene[] = scenesData.map((s: any, i: number) => ({
          id: s.id || `s-${i}`,
          visual_description: s.visual_description,
          narration: s.narration,
          narration_enabled: !!s.narration,
          music_description: s.music_description,
          music_enabled: !!s.music_description,
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
        const detail = err instanceof Error ? err.message : String(err)
        setAnalysisError(`Gemini analysis failed: ${detail}`)
        setIsAnalyzing(false)
      })
  }, [scenes.length, isAnalyzing, isReadOnly, tempProjectData, id, setTempProjectData])

  const onGenerateAll = async () => {
    const productionId = (tempProjectData as any)?.id || id
    if (!productionId || scenes.length === 0) return
    setIsStartingRender(true)
    setGenerateError(null)
    try {
      await api.projects.render(productionId)
      const updated = await api.projects.get(productionId)
      if (updated) setTempProjectData({ ...updated, scenes: updated.scenes || [] })
    } catch (err) {
      console.error('Failed to start render:', err)
      setGenerateError(err instanceof Error ? err.message : 'Failed to start generation')
    } finally {
      setIsStartingRender(false)
    }
  }

  // Poll production status while generating/stitching — backend handles the full state machine
  useEffect(() => {
    const productionId = (tempProjectData as any)?.id || id
    const status = (tempProjectData as any)?.status
    if (!productionId || (status !== 'generating' && status !== 'stitching')) return

    const pollInterval = setInterval(async () => {
      try {
        const prod = await api.projects.get(productionId)
        if (!prod) return
        setTempProjectData({ ...prod, scenes: prod.scenes || [] })

        if (prod.status === 'completed' || prod.status === 'failed') {
          if (prod.status === 'failed') {
            setGenerateError((prod as any).error_message || 'Generation failed')
          }
          clearInterval(pollInterval)
        }
      } catch (err) {
        console.error('Poll failed:', err)
      }
    }, 10000)

    return () => clearInterval(pollInterval)
  }, [(tempProjectData as any)?.status, (tempProjectData as any)?.id, id])

  const totalUsage = (tempProjectData as any)?.total_usage
  const inputTokens = totalUsage?.input_tokens || 0
  const outputTokens = totalUsage?.output_tokens || 0
  const estimatedCost = totalUsage?.cost_usd || 0
  const imageGenerations = totalUsage?.image_generations || 0
  const imageCost = totalUsage?.image_cost_usd || 0
  const veoVideos = totalUsage?.veo_videos || 0
  const veoSeconds = totalUsage?.veo_seconds || 0
  const veoUnitCost = totalUsage?.veo_unit_cost || 0
  const veoCost = totalUsage?.veo_cost_usd || 0

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

          <div className="hidden md:flex items-center px-4 border-r border-border">
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
          
          {(() => {
            const s = (tempProjectData as any)?.status
            const completedScenes = scenes.filter((sc: any) => sc.status === 'completed').length
            const framesReady = scenes.filter((sc: any) => sc.thumbnail_url).length
            if (s === 'generating') {
              const currentScene = scenes.find((sc: any) => sc.status === 'generating_frame' || sc.status === 'generating')
              const phase = currentScene?.status === 'generating_frame' ? 'Generating Frames' : 'Generating Videos'
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  {phase}... {completedScenes}/{scenes.length} scenes
                </div>
              )
            }
            if (s === 'stitching') {
              return (
                <div className="flex items-center gap-2 text-sm text-accent-dark font-medium">
                  <Loader2 className="animate-spin" size={16} />
                  Stitching Final Video...
                </div>
              )
            }
            if (s === 'completed') {
              return (
                <Button icon={Play} onClick={() => navigate(`/productions/${id}`)}>
                  View Final Video
                </Button>
              )
            }
            if (s === 'failed') {
              const errMsg = generateError || (tempProjectData as any)?.error_message || 'Generation failed'
              return (
                <div className="flex items-center gap-3">
                  <ErrorBadge message={errMsg} />
                  {isMaster && (
                    <Button icon={isStartingRender ? Loader2 : RotateCcw} onClick={onGenerateAll} disabled={isStartingRender}>
                      {isStartingRender ? 'Starting...' : 'Retry'}
                    </Button>
                  )}
                </div>
              )
            }
            if (!isMaster) return null
            const totalCredits = scenes.length * 7 // 2 (frame) + 5 (video) per scene
            return (
              <Button icon={isStartingRender ? Loader2 : Play} onClick={onGenerateAll} disabled={isStartingRender}>
                {isStartingRender ? 'Starting...' : `Generate All (${totalCredits} credits)`}
              </Button>
            )
          })()}
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
                productionId={(tempProjectData as any)?.id || id || ''}
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
