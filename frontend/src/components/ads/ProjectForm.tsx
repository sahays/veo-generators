import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import { ArrowLeft, Sparkles, FileText, ImageIcon, Monitor, Smartphone, Clock, Clapperboard, Megaphone, Share2, Play, Settings, Loader2, X, Upload, FolderOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { projectSchema, type ProjectFormData, VIDEO_LENGTH_OPTIONS, type SystemResource, type Scene, type UploadRecord } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { Select } from '@/components/UI'
import { ResourceModal } from './ResourceModal'

const CATEGORY_MAP: Record<string, string> = {
  movie: 'production-movie',
  advertizement: 'production-ad',
  social: 'production-social',
}

export const ProjectForm = () => {
  const { setTempProjectData, setActiveProject } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [existingProject, setExistingProject] = useState<any>(null)
  const [isLoadingProject, setIsLoadingProject] = useState(!!id)

  const [referenceImage, setReferenceImage] = useState<{ gcs_uri: string; signed_url: string } | null>(null)
  const [existingImages, setExistingImages] = useState<UploadRecord[]>([])
  const [showImagePicker, setShowImagePicker] = useState(false)
  const [isUploadingRef, setIsUploadingRef] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchResources = async () => {
    try {
      const allResources = await api.system.listResources()
      const pList = allResources.filter((r: SystemResource) => r.type === 'prompt')
      setPrompts(pList)

      // Set default active prompt for new projects
      if (!id) {
        const activePrompt = pList.find(p => p.is_active)
        if (activePrompt) setValue('prompt_id', activePrompt.id)
      }
    } catch (err) {
      console.error("Failed to fetch system resources", err)
    }
  }

  useEffect(() => {
    fetchResources()
    api.uploads.list({ file_type: 'image' }).then(setExistingImages).catch(() => {})
  }, [])

  // Fetch existing project from API when editing
  useEffect(() => {
    if (!id) return
    setIsLoadingProject(true)
    api.projects.get(id)
      .then((project) => {
        if (project && project.id) {
          setExistingProject(project)
          setActiveProject(id)
        }
      })
      .catch((err) => console.error('Failed to load production', err))
      .finally(() => setIsLoadingProject(false))
  }, [id, setActiveProject])

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors },
  } = useForm<ProjectFormData>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      name: '',
      type: 'advertizement',
      base_concept: '',
      video_length: '16',
      orientation: '16:9',
    },
  })

  // Reset form when existing project loads from API
  useEffect(() => {
    if (existingProject) {
      reset({
        name: existingProject.name,
        type: existingProject.type || 'advertizement',
        base_concept: existingProject.base_concept,
        video_length: existingProject.video_length || '16',
        orientation: existingProject.orientation || '16:9',
      })
      if (existingProject.reference_image_url) {
        setReferenceImage({
          gcs_uri: '',
          signed_url: existingProject.reference_image_url,
        })
      }
    }
  }, [existingProject, reset])

  const orientation = watch('orientation')
  const projectType = watch('type')
  const concept = watch('base_concept') || ''

  const [isSubmitting, setIsSubmitting] = useState(false)

  // Filter prompts by selected production type
  const filteredPrompts = prompts.filter(p => p.category === CATEGORY_MAP[projectType])

  // Auto-select first prompt or clear selection when production type changes
  useEffect(() => {
    const category = CATEGORY_MAP[projectType]
    const matching = prompts.filter(p => p.category === category)
    const currentPromptId = watch('prompt_id')
    if (!currentPromptId || !matching.find(p => p.id === currentPromptId)) {
      setValue('prompt_id', matching[0]?.id || '')
    }
  }, [projectType, prompts])

  const handleRefUpload = async (file: File) => {
    setIsUploadingRef(true)
    setUploadProgress(0)
    try {
      const { promise } = api.assets.directUpload(file, setUploadProgress)
      const result = await promise
      setReferenceImage({ gcs_uri: result.gcs_uri, signed_url: result.signed_url })
      // Refresh image list so it appears in the picker
      api.uploads.list({ file_type: 'image' }).then(setExistingImages).catch(() => {})
    } catch (err) {
      console.error('Reference image upload failed', err)
    } finally {
      setIsUploadingRef(false)
      setUploadProgress(0)
    }
  }

  const onAnalyze = handleSubmit(async (data) => {
    if (existingProject) {
      // Existing project — just pass through to script page
      setTempProjectData({ ...data, id, scenes: existingProject.scenes, prompt_id: data.prompt_id })
      navigate(`/productions/${id}/script`)
      return
    }

    // New project — create via API first
    setIsSubmitting(true)
    try {
      const created = await api.projects.create({
        name: data.name,
        type: data.type,
        base_concept: data.base_concept,
        video_length: data.video_length,
        orientation: data.orientation,
        ...(referenceImage?.gcs_uri ? { reference_image_url: referenceImage.gcs_uri } : {}),
      })
      setTempProjectData({ ...data, id: created.id, prompt_id: data.prompt_id })
      navigate(`/productions/${created.id}/script`)
    } catch (err) {
      console.error('Failed to create production', err)
    } finally {
      setIsSubmitting(false)
    }
  })

  if (isLoadingProject) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading production...</p>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6 max-w-3xl mx-auto"
    >
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/productions')} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="text-xl font-heading text-foreground tracking-tight">
            {existingProject ? 'Edit Production' : 'New Production'}
          </h2>
          <p className="text-xs text-muted-foreground">
            {existingProject ? 'Update your production settings' : 'Define your core concept and technical constraints.'}
          </p>
        </div>
      </div>

      <form className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card title="Production Type" icon={projectType === 'movie' ? Clapperboard : projectType === 'social' ? Share2 : Megaphone} className="md:col-span-3">
            <div className="flex flex-wrap gap-4">
              {[
                { id: 'movie', label: 'Movie', icon: Clapperboard, desc: 'Cinematic storytelling' },
                { id: 'advertizement', label: 'Ad', icon: Megaphone, desc: 'Brand promotion' },
                { id: 'social', label: 'Social', icon: Share2, desc: 'Viral short content' }
              ].map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setValue('type', opt.id as any)}
                  className={cn(
                    "flex-1 flex items-center gap-3 p-3 rounded-xl border transition-all text-left",
                    projectType === opt.id 
                      ? "bg-accent/10 border-accent text-accent-dark shadow-sm" 
                      : "border-border text-muted-foreground hover:border-accent/30"
                  )}
                >
                  <div className={cn(
                    "p-2 rounded-lg",
                    projectType === opt.id ? "bg-accent text-slate-900" : "bg-muted"
                  )}>
                    <opt.icon size={18} />
                  </div>
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-wider">{opt.label}</p>
                    <p className="text-[10px] opacity-70">{opt.desc}</p>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <Card title="Concept & Vision" icon={FileText}>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Project Name</label>
              <input
                {...register('name')}
                placeholder="Summer Campaign 2026"
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border focus:ring-2 focus:ring-accent/30 outline-none"
              />
              {errors.name && <p className="text-[10px] text-red-500">{errors.name.message}</p>}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Base Concept</label>
                <span className="text-[10px] font-mono text-muted-foreground">{concept.length}/2000</span>
              </div>
              <textarea
                {...register('base_concept')}
                rows={5}
                placeholder="Describe the overall story, vibe, and key message..."
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border focus:ring-2 focus:ring-accent/30 outline-none resize-none"
              />
              {errors.base_concept && <p className="text-[10px] text-red-500">{errors.base_concept.message}</p>}
            </div>
          </div>
        </Card>

        <Card title="System Configuration" icon={Settings} className="relative z-20">
          <Select
            label="Prompt"
            value={watch('prompt_id') || ''}
            onChange={(val) => {
              if (val === 'CREATE_NEW') {
                setIsModalOpen(true)
              } else {
                setValue('prompt_id', val)
              }
            }}
            options={[
              ...filteredPrompts.map(p => ({
                value: p.id,
                label: p.name,
                description: `Version ${p.version}`
              })),
              { value: 'CREATE_NEW', label: '+ Create New Prompt...', className: 'text-accent-dark font-bold bg-accent/5' }
            ]}
          />
        </Card>

        <ResourceModal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          type="prompt"
          existingResources={prompts}
          onSuccess={(saved) => {
            fetchResources()
            setValue('prompt_id', saved.id)
          }}
        />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card title="Duration" icon={Clock}>
            <div className="flex flex-wrap gap-3">
              {VIDEO_LENGTH_OPTIONS.map((len) => (
                <label key={len} className="flex items-center gap-2 cursor-pointer group">
                  <input
                    type="radio"
                    value={len}
                    {...register('video_length')}
                    className="sr-only"
                  />
                  <div className={cn(
                    "px-3 py-1.5 rounded-md border text-xs font-medium transition-all",
                    watch('video_length') === len 
                      ? "bg-accent text-slate-900 border-accent"
                      : "border-border hover:border-accent/50 text-muted-foreground"
                  )}>
                    {len === 'custom' ? 'Custom' : `${len}s`}
                  </div>
                </label>
              ))}
            </div>
          </Card>

          <Card title="Orientation" icon={orientation === '16:9' ? Monitor : Smartphone}>
            <div className="flex gap-4">
              {[
                { id: '16:9', label: 'Landscape', icon: Monitor },
                { id: '9:16', label: 'Vertical', icon: Smartphone }
              ].map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setValue('orientation', opt.id as any)}
                  className={cn(
                    "flex-1 flex flex-col items-center gap-2 p-3 rounded-xl border transition-all",
                    orientation === opt.id 
                      ? "bg-accent/10 border-accent text-accent-dark" 
                      : "border-border text-muted-foreground hover:border-accent/30"
                  )}
                >
                  <opt.icon size={20} />
                  <span className="text-[10px] font-bold uppercase tracking-widest">{opt.label}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <Card title="Visual Reference" icon={ImageIcon}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) handleRefUpload(file)
              e.target.value = ''
            }}
          />

          {referenceImage ? (
            <div className="relative group">
              <img
                src={referenceImage.signed_url}
                alt="Reference"
                className="w-full max-h-48 object-contain rounded-lg border border-border"
              />
              <button
                type="button"
                onClick={() => setReferenceImage(null)}
                className="absolute top-2 right-2 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/80"
              >
                <X size={14} />
              </button>
            </div>
          ) : isUploadingRef ? (
            <div className="border-2 border-dashed border-accent/40 rounded-xl p-8 flex flex-col items-center justify-center space-y-3">
              <Loader2 className="animate-spin text-accent" size={24} />
              <div className="w-48 h-1.5 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-accent rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-[10px] text-muted-foreground">Uploading... {uploadProgress}%</p>
            </div>
          ) : showImagePicker ? (
            <div className="space-y-3">
              {existingImages.length > 0 ? (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-48 overflow-y-auto">
                  {existingImages.map((img) => (
                    <button
                      key={img.id}
                      type="button"
                      onClick={() => {
                        setReferenceImage({ gcs_uri: img.gcs_uri, signed_url: img.signed_url || '' })
                        setShowImagePicker(false)
                      }}
                      className="aspect-square rounded-lg overflow-hidden border border-border hover:border-accent transition-colors"
                    >
                      <img src={img.signed_url} alt={img.filename} className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground text-center py-4">No images in Files yet.</p>
              )}
              <button
                type="button"
                onClick={() => setShowImagePicker(false)}
                className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="border-2 border-dashed border-border rounded-xl p-8 flex flex-col items-center justify-center text-center space-y-3 hover:border-accent/50 transition-colors">
              <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-muted-foreground">
                <ImageIcon size={20} />
              </div>
              <p className="text-[10px] text-muted-foreground">Provide a visual anchor for characters and style.</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium hover:border-accent/50 hover:text-accent-dark transition-colors"
                >
                  <Upload size={13} />
                  Upload New
                </button>
                <button
                  type="button"
                  onClick={() => setShowImagePicker(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-medium hover:border-accent/50 hover:text-accent-dark transition-colors"
                >
                  <FolderOpen size={13} />
                  Choose from Files
                </button>
              </div>
            </div>
          )}
        </Card>

        {/* Storyboard Preview for existing projects */}
        {existingProject && existingProject.scenes.length > 0 && (
          <Card title="Storyboard Preview" icon={Clapperboard}>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {existingProject.scenes.map((scene: Scene) => (
                <div key={scene.id} className="group relative aspect-video rounded-lg overflow-hidden border border-border bg-muted">
                  <img src={scene.thumbnail_url} className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col justify-end p-2">
                    <span className="text-[8px] text-white font-mono">{scene.timestamp_start}</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        <div className="flex justify-end pt-4">
          <Button
            onClick={onAnalyze}
            icon={existingProject?.scenes.length ? Play : Sparkles}
            className="w-full md:w-auto"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Creating...' : existingProject?.scenes.length ? 'View & Edit Script' : 'Generate Scenes'}
          </Button>
        </div>
      </form>
    </motion.div>
  )
}
