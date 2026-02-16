import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import { ArrowLeft, Sparkles, FileText, ImageIcon, Monitor, Smartphone, Clock, Clapperboard, Megaphone, Share2, Play, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { projectSchema, type ProjectFormData, VIDEO_LENGTH_OPTIONS, type SystemResource } from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export const ProjectForm = () => {
  const { setTempProjectData, setActiveProject, projects } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  
  const [prompts, setPrompts] = useState<SystemResource[]>([])
  const [schemas, setSchemas] = useState<SystemResource[]>([])

  useEffect(() => {
    const fetchResources = async () => {
      try {
        const [pList, sList] = await Promise.all([
          api.system.listResources('prompt', 'project-analysis'),
          api.system.listResources('schema', 'project-analysis')
        ])
        setPrompts(pList)
        setSchemas(sList)

        // Set default values for new projects
        if (!id) {
          const activePrompt = pList.find(p => p.is_active)
          const activeSchema = sList.find(s => s.is_active)
          if (activePrompt) setValue('prompt_id', activePrompt.id)
          if (activeSchema) setValue('schema_id', activeSchema.id)
        }
      } catch (err) {
        console.error("Failed to fetch system resources", err)
      }
    }
    fetchResources()
  }, [])

  const existingProject = id ? projects.find(p => p.id === id) : null

  useEffect(() => {
    if (id && existingProject) {
      setActiveProject(id)
    }
  }, [id, existingProject, setActiveProject])

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<ProjectFormData>({
    resolver: zodResolver(projectSchema),
    defaultValues: {
      name: existingProject?.name || '',
      type: existingProject?.type || 'advertizement',
      base_concept: existingProject?.base_concept || '',
      video_length: existingProject?.video_length || '16',
      orientation: existingProject?.orientation || '16:9',
    },
  })

  const orientation = watch('orientation')
  const projectType = watch('type')
  const concept = watch('base_concept') || ''

  const onAnalyze = handleSubmit((data) => {
    setTempProjectData({ ...data, scenes: existingProject?.scenes })
    navigate(id ? `/productions/${id}/script` : '/productions/new/script')
  })

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

        <Card title="System Configuration" icon={Settings}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Analysis Prompt</label>
              <select
                {...register('prompt_id')}
                onChange={(e) => {
                  if (e.target.value === 'CREATE_NEW') {
                    navigate('/prompts');
                  } else {
                    setValue('prompt_id', e.target.value);
                  }
                }}
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border focus:ring-2 focus:ring-accent/30 outline-none appearance-none"
              >
                {prompts.map(p => (
                  <option key={p.id} value={p.id} className="bg-slate-900">
                    {p.name} {p.is_active ? '(Active)' : `v${p.version}`}
                  </option>
                ))}
                <option value="CREATE_NEW" className="bg-slate-900 text-accent font-bold">
                  + Create New Prompt...
                </option>
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Output Schema</label>
              <select
                {...register('schema_id')}
                onChange={(e) => {
                  if (e.target.value === 'CREATE_NEW') {
                    navigate('/prompts');
                  } else {
                    setValue('schema_id', e.target.value);
                  }
                }}
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border focus:ring-2 focus:ring-accent/30 outline-none appearance-none"
              >
                {schemas.map(s => (
                  <option key={s.id} value={s.id} className="bg-slate-900">
                    {s.name} {s.is_active ? '(Active)' : `v${s.version}`}
                  </option>
                ))}
                <option value="CREATE_NEW" className="bg-slate-900 text-accent font-bold">
                  + Create New Schema...
                </option>
              </select>
            </div>
          </div>
        </Card>

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
          <div className="border-2 border-dashed border-border rounded-xl p-8 flex flex-col items-center justify-center text-center space-y-2 hover:border-accent/50 transition-colors cursor-pointer">
            <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-muted-foreground">
              <ImageIcon size={20} />
            </div>
            <p className="text-xs font-medium">Upload Key Reference Image</p>
            <p className="text-[10px] text-muted-foreground">Provide a visual anchor for characters and style.</p>
          </div>
        </Card>

        {/* Storyboard Preview for existing projects */}
        {existingProject && existingProject.scenes.length > 0 && (
          <Card title="Storyboard Preview" icon={Clapperboard}>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {existingProject.scenes.map((scene) => (
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
          >
            {existingProject?.scenes.length ? 'View & Edit Script' : 'Analyze & Script'}
          </Button>
        </div>
      </form>
    </motion.div>
  )
}
