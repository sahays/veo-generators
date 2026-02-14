import { useState, useCallback } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import { ArrowLeft, Save, Sparkles, Dices, FileText, ImageIcon, Sliders, Clapperboard } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { MediaDropZone } from './MediaDropZone'
import { CreativeSettings } from './CreativeSettings'
import { StoryboardView } from './StoryboardView'
import { useProjectStore } from '@/store/useProjectStore'
import { projectSchema, type Project, type ProjectFormData, type MediaFile, type StoryboardFrame } from '@/types/project'
import { generateStoryboardFrames } from '@/lib/mockData'

export const ProjectForm = () => {
  const { activeProjectId, projects, addProject, updateProject, setView } = useProjectStore()
  const existingProject = activeProjectId
    ? projects.find((p) => p.id === activeProjectId)
    : null

  const [mediaFiles, setMediaFiles] = useState<MediaFile[]>([])
  const [storyboardFrames, setStoryboardFrames] = useState<StoryboardFrame[]>(
    existingProject?.storyboardFrames || [],
  )
  const [isGenerating, setIsGenerating] = useState(false)

  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { errors },
  } = useForm<ProjectFormData>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      name: existingProject?.name || '',
      prompt: existingProject?.prompt || '',
      directorStyle: existingProject?.directorStyle || '',
      cameraMovement: existingProject?.cameraMovement || '',
      mood: existingProject?.mood || '',
      location: existingProject?.location || '',
      characterAppearance: existingProject?.characterAppearance || '',
      videoLength: existingProject?.videoLength || '16',
    },
  })

  const promptValue = watch('prompt') || ''
  const videoLength = watch('videoLength')
  const directorStyle = watch('directorStyle')
  const cameraMovement = watch('cameraMovement')
  const mood = watch('mood')
  const location = watch('location')
  const characterAppearance = watch('characterAppearance')

  const handleCreativeChange = useCallback(
    (field: string, value: string) => {
      setValue(field as keyof ProjectFormData, value, { shouldValidate: true })
    },
    [setValue],
  )

  const buildProject = (data: ProjectFormData, status: Project['status'], id?: string): Project => ({
    id: id || `proj-${Date.now()}`,
    name: data.name,
    prompt: data.prompt,
    directorStyle: data.directorStyle,
    cameraMovement: data.cameraMovement,
    mood: data.mood,
    location: data.location,
    characterAppearance: data.characterAppearance,
    videoLength: data.videoLength,
    status,
    mediaFiles,
    storyboardFrames: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  })

  const onSaveDraft = handleSubmit((data) => {
    if (existingProject) {
      updateProject(existingProject.id, { ...data, status: 'draft', mediaFiles })
    } else {
      addProject(buildProject(data, 'draft'))
    }
    setView('list')
  })

  const onGenerate = handleSubmit((data) => {
    setIsGenerating(true)
    setStoryboardFrames([])

    const projectId = existingProject?.id || `proj-${Date.now()}`

    if (existingProject) {
      updateProject(projectId, { ...data, status: 'generating', mediaFiles })
    } else {
      addProject(buildProject(data, 'generating', projectId))
    }

    // Mock generation
    setTimeout(() => {
      const frames = generateStoryboardFrames(6, data.name || 'untitled')
      setStoryboardFrames(frames)
      setIsGenerating(false)
      updateProject(projectId, {
        status: 'completed',
        storyboardFrames: frames,
      })
    }, 3000)
  })

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.2 }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setView('list')}
          className="p-1.5 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="text-xl font-heading text-foreground tracking-tight">
            {existingProject ? 'Edit Project' : 'New Project'}
          </h2>
          <p className="text-xs text-muted-foreground">
            {existingProject ? 'Update your ad generation settings' : 'Configure your new ad generation'}
          </p>
        </div>
      </div>

      <form className="space-y-6">
        {/* Project Details */}
        <Card title="Project Details" icon={FileText}>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-xs font-medium text-muted-foreground">
                Project Name
              </label>
              <input
                id="name"
                {...register('name')}
                placeholder="My Ad Campaign"
                className={cn(
                  "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 text-foreground",
                  "glass bg-card border border-border placeholder:text-muted-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50",
                  errors.name && "border-red-500/50 focus:ring-red-500/30"
                )}
              />
              {errors.name && (
                <p className="text-[11px] text-red-500">{errors.name.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label htmlFor="prompt" className="text-xs font-medium text-muted-foreground">
                  Prompt
                </label>
                <span className={cn(
                  "text-[10px] font-mono",
                  promptValue.length > 1800 ? "text-amber-500" : "text-muted-foreground"
                )}>
                  {promptValue.length}/2000
                </span>
              </div>
              <textarea
                id="prompt"
                {...register('prompt')}
                rows={4}
                placeholder="Describe the video you want to generate..."
                className={cn(
                  "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 resize-none text-foreground",
                  "glass bg-card border border-border placeholder:text-muted-foreground",
                  "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50",
                  errors.prompt && "border-red-500/50 focus:ring-red-500/30"
                )}
              />
              {errors.prompt && (
                <p className="text-[11px] text-red-500">{errors.prompt.message}</p>
              )}
            </div>
          </div>
        </Card>

        {/* Reference Media */}
        <Card title="Reference Media" icon={ImageIcon}>
          <Controller
            name="name" // dummy — media not in schema
            control={control}
            render={() => (
              <MediaDropZone files={mediaFiles} onChange={setMediaFiles} />
            )}
          />
        </Card>

        {/* Creative Settings */}
        <Card title="Creative Settings" icon={Sliders}>
          <CreativeSettings
            values={{
              directorStyle,
              cameraMovement,
              mood,
              location,
              characterAppearance,
              videoLength,
            }}
            onChange={handleCreativeChange}
          />
        </Card>

        {/* Storyboard */}
        {(isGenerating || storyboardFrames.length > 0) && (
          <Card title="Storyboard" icon={Clapperboard}>
            <StoryboardView frames={storyboardFrames} isGenerating={isGenerating} />
          </Card>
        )}

        {/* Action Bar */}
        <div className="flex items-center justify-between pt-2 pb-4">
          <Button
            variant="ghost"
            onClick={() => setView('list')}
            type="button"
          >
            Cancel
          </Button>
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              icon={Save}
              onClick={onSaveDraft}
              type="button"
            >
              Save Draft
            </Button>
            <Button
              icon={Sparkles}
              onClick={onGenerate}
              type="button"
              disabled={isGenerating}
            >
              {isGenerating ? 'Generating...' : 'Start Storyboarding'}
            </Button>
            <Button
              icon={Dices}
              onClick={onGenerate}
              type="button"
              disabled={isGenerating}
              className="bg-accent-light text-foreground hover:bg-accent/30 shadow-sm"
            >
              I'm feeling lucky!
            </Button>
          </div>
        </div>
      </form>
    </motion.div>
  )
}
