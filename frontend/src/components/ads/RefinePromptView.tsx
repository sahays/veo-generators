import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, Sparkles, Video, Play, ImageIcon, Save } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

export const RefinePromptView = () => {
  const { tempProjectData, setView, activeProjectId, updateProject } = useProjectStore()
  const [prompt, setPrompt] = useState(tempProjectData?.prompt || '')
  const queryClient = useQueryClient()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [prompt])

  const optimizeMutation = useMutation({
    mutationFn: () => api.ai.optimizePrompt({
      raw_prompt: tempProjectData?.prompt || '',
      director_style: tempProjectData?.directorStyle,
      mood: tempProjectData?.mood,
      location: tempProjectData?.location,
      camera_movement: tempProjectData?.cameraMovement,
    }),
    onSuccess: (data) => {
      setPrompt(data.refined_prompt)
    }
  })

  const storyboardMutation = useMutation({
    mutationFn: () => api.ai.generateStoryboard({
      project_id: activeProjectId || `proj-${Date.now()}`,
      refined_prompt: prompt,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setView('list')
    }
  })

  const videoMutation = useMutation({
    mutationFn: () => api.ai.generateVideo({
      project_id: activeProjectId || `proj-${Date.now()}`,
      refined_prompt: prompt,
      video_length: tempProjectData?.videoLength || '16',
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      setView('list')
    }
  })

  const handleSave = async () => {
    if (activeProjectId) {
      await api.projects.update(activeProjectId, { refined_prompt: prompt })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    }
    setView('form')
  }

  const isAnyActionLoading = optimizeMutation.isPending || storyboardMutation.isPending || videoMutation.isPending

  return (
    <motion.div
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="max-w-4xl mx-auto space-y-8 pb-12"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setView('form')}
            className="p-2 hover:bg-muted rounded-xl transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h2 className="text-2xl font-heading text-foreground tracking-tight">Refine Production</h2>
            <p className="text-sm text-muted-foreground">Finalize your screenplay and production details.</p>
          </div>
        </div>
        <Button variant="ghost" icon={Save} onClick={handleSave} disabled={isAnyActionLoading}>
          Save Changes
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-8">
        {/* Detailed Prompt Editor */}
        <Card title="Detailed Screenplay" icon={FileTextIcon}>
          <div className="space-y-4">
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={isAnyActionLoading}
              className={cn(
                "w-full min-h-[200px] p-4 rounded-xl text-sm font-mono leading-relaxed transition-all duration-300",
                "bg-card border border-border focus:ring-2 focus:ring-accent/30 outline-none",
                "resize-none overflow-hidden",
                isAnyActionLoading && "opacity-50 cursor-not-allowed"
              )}
              placeholder="Describe your scene in detail..."
            />
            <div className="flex justify-start">
              <Button 
                onClick={() => optimizeMutation.mutate()} 
                disabled={isAnyActionLoading}
                variant="secondary"
                icon={Sparkles}
                className="bg-accent/10 hover:bg-accent/20 border-accent/20"
              >
                {optimizeMutation.isPending ? 'Optimizing Screenplay...' : 'Optimize for Veo'}
              </Button>
            </div>
          </div>
        </Card>

        {/* Media Preview */}
        {tempProjectData?.mediaFiles && tempProjectData.mediaFiles.length > 0 && (
          <Card title="Reference Assets" icon={ImageIcon}>
            <div className="flex gap-4 overflow-x-auto pb-2 no-scrollbar">
              {tempProjectData.mediaFiles.map((file: any) => (
                <div key={file.id} className="relative w-32 h-32 shrink-0 rounded-lg overflow-hidden border border-border">
                  <img src={file.previewUrl} alt="Preview" className="w-full h-full object-cover" />
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Final Actions */}
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 pt-6">
          <div className="text-sm text-muted-foreground italic">
            Ready to start production? Choose your output format.
          </div>
          <div className="flex items-center gap-4 w-full md:w-auto">
            <Button 
              variant="secondary" 
              icon={ImageIcon} 
              className="flex-1 md:flex-none"
              onClick={() => storyboardMutation.mutate()}
              disabled={isAnyActionLoading}
            >
              {storyboardMutation.isPending ? 'Processing...' : 'Generate Storyboard'}
            </Button>
            <Button 
              icon={Play} 
              className="flex-1 md:flex-none"
              onClick={() => videoMutation.mutate()}
              disabled={isAnyActionLoading}
            >
              {videoMutation.isPending ? 'Starting Render...' : 'Final Video Generation'}
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

const FileTextIcon = (props: any) => (
  <svg
    {...props}
    xmlns="http://www.w3.org/2000/svg"
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <line x1="10" y1="9" x2="8" y2="9" />
  </svg>
)
