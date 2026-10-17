import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Sparkles,
  FileText,
  Monitor,
  Smartphone,
  Clock,
  Clapperboard,
  Megaphone,
  Share2,
  Play,
  Loader2,
  Globe,
  GitBranch,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useProjectStore } from '@/store/useProjectStore'
import {
  projectSchema,
  type ProjectFormData,
  VIDEO_LENGTH_OPTIONS,
  PRODUCTION_LANGUAGES,
} from '@/types/project'
import { useNavigate, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'

export const ProjectForm = () => {
  const { setTempProjectData, setActiveProject } = useProjectStore()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const [existingProject, setExistingProject] = useState<any>(null)
  const [isLoadingProject, setIsLoadingProject] = useState(!!id)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (!id) return
    setIsLoadingProject(true)
    api.projects
      .get(id)
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
      type: 'movie',
      base_concept: '',
      video_length: '16',
      orientation: '16:9',
      language: 'en-IN',
      auto_approve_gates: false,
    },
  })

  useEffect(() => {
    if (existingProject) {
      reset({
        name: existingProject.name,
        type: existingProject.type || 'movie',
        base_concept: existingProject.base_concept,
        video_length: String(existingProject.video_length || '16'),
        orientation: existingProject.orientation || '16:9',
        language: existingProject.language || 'en-IN',
        auto_approve_gates: Boolean(existingProject.auto_approve_gates),
      })
    }
  }, [existingProject, reset])

  const orientation = watch('orientation')
  const projectType = watch('type')
  const language = watch('language') || 'en-IN'
  const concept = watch('base_concept') || ''

  const onLaunchStudio = handleSubmit(async (data) => {
    setIsSubmitting(true)
    try {
      if (existingProject && id) {
        await api.projects.update(id, {
          name: data.name,
          type: data.type,
          base_concept: data.base_concept,
          video_length: data.video_length,
          orientation: data.orientation,
          language: data.language,
          auto_approve_gates: Boolean(data.auto_approve_gates),
        } as any)
        setTempProjectData({
          ...existingProject,
          ...data,
          id,
        } as any)
        navigate(`/productions/${id}/script`)
        return
      }

      const created = await api.projects.create({
        name: data.name,
        type: data.type,
        base_concept: data.base_concept,
        video_length: data.video_length,
        orientation: data.orientation,
        language: data.language,
        auto_approve_gates: Boolean(data.auto_approve_gates),
      } as any)
      setTempProjectData({
        ...data,
        id: created.id,
      } as any)
      navigate(`/productions/${created.id}/script`)
    } catch (err) {
      console.error('Failed to save production', err)
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
      className="space-y-6 max-w-3xl mx-auto pb-20"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate('/productions')}>
            <ArrowLeft size={18} />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-heading text-foreground tracking-tight">
                {existingProject ? 'Edit Production Brief' : 'New Story-to-Video Production'}
              </h2>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-accent/10 text-accent-dark border border-accent/25 text-[10px] font-mono font-bold uppercase">
                <GitBranch size={11} /> StoryGraph v1
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              Provide a story idea or script. The 10-stage multi-agent StoryGraph studio will extract entities, design reference sheets, direct shots, and compile deterministic prompts.
            </p>
          </div>
        </div>
      </div>

      <form className="space-y-6">
        <Card
          title="Production Format"
          icon={projectType === 'movie' ? Clapperboard : projectType === 'social' ? Share2 : Megaphone}
        >
          <div className="flex flex-wrap gap-4">
            {[
              { id: 'movie', label: 'Movie / Short Film', icon: Clapperboard, desc: 'Narrative multi-scene storytelling' },
              { id: 'advertizement', label: 'Brand Commercial', icon: Megaphone, desc: 'High-impact product & brand story' },
              { id: 'social', label: 'Social Reel', icon: Share2, desc: 'Fast-paced short-form story' },
            ].map((opt) => (
              <Button
                variant="unstyled"
                key={opt.id}
                type="button"
                onClick={() => setValue('type', opt.id as any)}
                className={cn(
                  'flex-1 flex items-center gap-3 p-3 rounded-[6px] border transition-all text-left',
                  projectType === opt.id
                    ? 'bg-accent/10 border-accent text-accent-dark shadow-sm'
                    : 'border-border text-muted-foreground hover:border-accent/30',
                )}
              >
                <div
                  className={cn(
                    'p-2 rounded-[5px]',
                    projectType === opt.id ? 'btn-primary text-white' : 'bg-muted',
                  )}
                >
                  <opt.icon size={18} />
                </div>
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wider">{opt.label}</p>
                  <p className="text-[10px] opacity-70">{opt.desc}</p>
                </div>
              </Button>
            ))}
          </div>
        </Card>

        <Card title="Story Concept & Narrative Brief" icon={FileText}>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Production Title
              </label>
              <Input
                {...register('name')}
                placeholder="e.g. Midnight Signal at Victoria Terminus"
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border"
              />
              {errors.name && <p className="text-[10px] text-red-500">{errors.name.message}</p>}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  Story Idea or Full Script
                </label>
                <span className="text-[10px] font-mono text-muted-foreground">
                  {concept.length}/2000
                </span>
              </div>
              <Textarea
                {...register('base_concept')}
                rows={6}
                placeholder="Describe characters, locations, props, key events, or paste a multi-scene story..."
                className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border resize-none"
              />
              {errors.base_concept && (
                <p className="text-[10px] text-red-500">{errors.base_concept.message}</p>
              )}
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card title="Target Duration" icon={Clock}>
            <div className="flex flex-wrap gap-2.5">
              {VIDEO_LENGTH_OPTIONS.filter((l) => l !== 'custom').map((len) => (
                <Button
                  key={len}
                  variant="unstyled"
                  type="button"
                  onClick={() => setValue('video_length', len)}
                  className={cn(
                    'px-3.5 py-2 rounded-[5px] border text-xs font-medium transition-all',
                    watch('video_length') === len
                      ? 'btn-primary text-white border-transparent'
                      : 'border-border hover:border-accent/50 text-muted-foreground',
                  )}
                >
                  {len}s
                </Button>
              ))}
            </div>
          </Card>

          <Card title="Aspect Ratio" icon={orientation === '16:9' ? Monitor : Smartphone}>
            <div className="flex gap-4">
              {[
                { id: '16:9', label: '16:9 Landscape', icon: Monitor },
                { id: '9:16', label: '9:16 Vertical', icon: Smartphone },
              ].map((opt) => (
                <Button
                  variant="unstyled"
                  key={opt.id}
                  type="button"
                  onClick={() => setValue('orientation', opt.id as any)}
                  className={cn(
                    'flex-1 flex flex-col items-center gap-2 p-3 rounded-[6px] border transition-all',
                    orientation === opt.id
                      ? 'bg-accent/10 border-accent text-accent-dark'
                      : 'border-border text-muted-foreground hover:border-accent/30',
                  )}
                >
                  <opt.icon size={20} />
                  <span className="text-[10px] font-bold uppercase tracking-widest">
                    {opt.label}
                  </span>
                </Button>
              ))}
            </div>
          </Card>
        </div>

        <Card title="Spoken Language & Studio Gate Mode" icon={Globe}>
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {PRODUCTION_LANGUAGES.map((langOpt) => (
                <Button
                  variant="unstyled"
                  key={langOpt.id}
                  type="button"
                  onClick={() => setValue('language', langOpt.id)}
                  className={cn(
                    'flex flex-col items-start gap-1 p-3 rounded-[6px] border transition-all text-left',
                    language === langOpt.id
                      ? 'bg-accent/10 border-accent text-accent-dark shadow-sm'
                      : 'border-border text-muted-foreground hover:border-accent/30',
                  )}
                >
                  <span className="text-xs font-bold">{langOpt.label}</span>
                  <span className="text-[10px] opacity-75">{langOpt.sub}</span>
                </Button>
              ))}
            </div>
            <div className="pt-3 border-t border-border/50 flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-bold text-foreground">Human-in-the-Loop Gate Mode</p>
                <p className="text-[10px] text-muted-foreground">
                  Pause for review at Gate G1 (Entities), Gate G2 (Reference Sheets), and Gate G3 (Shots & Prompts), or auto-approve all gates.
                </p>
              </div>
              <div className="flex items-center gap-2">
                {[
                  { val: false, label: 'Interactive Gates (G1 · G2 · G3)' },
                  { val: true, label: 'Auto-Approve Gates' },
                ].map((opt) => (
                  <Button
                    key={String(opt.val)}
                    type="button"
                    size="xs"
                    variant={Boolean(watch('auto_approve_gates')) === opt.val ? 'primary' : 'outline'}
                    onClick={() => setValue('auto_approve_gates', opt.val)}
                  >
                    {opt.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </Card>

        <div className="flex justify-end gap-3 pt-2">
          <Button
            onClick={onLaunchStudio}
            icon={existingProject ? Play : Sparkles}
            className="w-full md:w-auto"
            disabled={isSubmitting}
          >
            {isSubmitting
              ? 'Launching Studio...'
              : existingProject
                ? 'Save & Open StoryGraph Studio'
                : 'Launch Story-to-Video Graph Studio'}
          </Button>
        </div>
      </form>
    </motion.div>
  )
}
