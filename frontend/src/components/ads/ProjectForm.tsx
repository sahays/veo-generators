import { useEffect, useState } from 'react'
import { useForm, type UseFormReturn } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import { ArrowLeft, Sparkles, Play, Loader2, GitBranch } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { projectSchema, type Project, type ProjectFormData } from '@/types/project'
import { useAdsProjectActions } from './projects/useAdsProjectActions'
import {
  ProductionFormatCard,
  StoryConceptCard,
  DurationAndAspectGrid,
  LanguageAndGateModeCard,
} from './projects/ProjectFormSections'
import { ProjectCreativePresetsCard } from './projects/ProjectCreativePresetsCard'

const DEFAULT_PROJECT_FORM_VALUES: ProjectFormData = {
  name: '',
  type: 'movie',
  base_concept: '',
  video_length: 'auto',
  orientation: '16:9',
  language: 'en-IN',
  visual_style_preset: 'superhero_blockbuster',
  color_palette_preset: 'warm_golden_amber',
  director_style_preset: 'wonder_humanist_blocking',
  screenplay_style_preset: 'classical_causal_chain',
  music_style_preset: 'symphonic_leitmotif_natural_foley',
  auto_approve_gates: false,
}

function mapProjectToFormValues(project: Project): ProjectFormData {
  return {
    name: project.name,
    type: project.type || 'movie',
    base_concept: project.base_concept,
    video_length: String(project.video_length || 'auto') as ProjectFormData['video_length'],
    orientation: project.orientation || '16:9',
    language: project.language || 'en-IN',
    visual_style_preset: project.visual_style_preset || 'superhero_blockbuster',
    color_palette_preset: project.color_palette_preset || 'warm_golden_amber',
    director_style_preset: project.director_style_preset || 'wonder_humanist_blocking',
    screenplay_style_preset: project.screenplay_style_preset || 'classical_causal_chain',
    music_style_preset: project.music_style_preset || 'symphonic_leitmotif_natural_foley',
    auto_approve_gates: Boolean(project.auto_approve_gates),
  }
}

function buildProjectPayload(data: ProjectFormData): Partial<Project> {
  return {
    name: data.name,
    type: data.type,
    base_concept: data.base_concept,
    video_length: data.video_length,
    orientation: data.orientation,
    language: data.language,
    visual_style_preset: data.visual_style_preset || 'superhero_blockbuster',
    color_palette_preset: data.color_palette_preset || 'warm_golden_amber',
    director_style_preset: data.director_style_preset || 'wonder_humanist_blocking',
    screenplay_style_preset: data.screenplay_style_preset,
    music_style_preset: data.music_style_preset,
    auto_approve_gates: Boolean(data.auto_approve_gates),
  }
}

function useLoadProjectIntoForm(id: string | undefined, form: UseFormReturn<ProjectFormData>) {
  const { setActiveProject } = useProjectStore()
  const { projects: projectsApi } = useAdsProjectActions()
  const [existingProject, setExistingProject] = useState<Project | null>(null)
  const [isLoadingProject, setIsLoadingProject] = useState(!!id)

  useEffect(() => {
    if (!id) return
    setIsLoadingProject(true)
    projectsApi
      .get(id)
      .then((project) => {
        if (project?.id) {
          setExistingProject(project)
          setActiveProject(id)
          form.reset(mapProjectToFormValues(project))
        }
      })
      .catch(() => null)
      .finally(() => setIsLoadingProject(false))
  }, [id, projectsApi, setActiveProject, form])

  return { existingProject, isLoadingProject }
}

function useSubmitProjectForm(id: string | undefined, existingProject: Project | null) {
  const { setTempProjectData } = useProjectStore()
  const { projects: projectsApi } = useAdsProjectActions()
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)

  const submitForm = async (data: ProjectFormData) => {
    setIsSubmitting(true)
    try {
      const payload = buildProjectPayload(data)
      if (existingProject && id) {
        await projectsApi.update(id, payload)
        setTempProjectData({ ...existingProject, ...data, id })
        navigate(`/productions/${id}/script`)
        return
      }
      const created = await projectsApi.create(payload)
      setTempProjectData({ ...data, id: created.id, scenes: [] })
      navigate(`/productions/${created.id}/script`)
    } finally {
      setIsSubmitting(false)
    }
  }

  return { isSubmitting, submitForm }
}

const ProjectFormView = ({
  form,
  existingProject,
  isSubmitting,
  onSubmit,
  onBack,
}: {
  form: UseFormReturn<ProjectFormData>
  existingProject: Project | null
  isSubmitting: boolean
  onSubmit: () => void
  onBack: () => void
}) => (
  <motion.div
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    exit={{ opacity: 0, x: -20 }}
    className="space-y-6 max-w-4xl mx-auto pb-20"
  >
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack}>
          <ArrowLeft size={18} />
        </Button>
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-heading text-foreground tracking-tight">
              {existingProject ? 'Edit Production Brief' : 'New Story-to-Video Production'}
            </h2>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-accent/10 text-accent-dark border border-accent/25 text-[10px] font-mono font-bold uppercase">
              <GitBranch size={11} /> Agent-First StoryGraph
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            Provide a story idea or script. Specialized AI crew agents (Architect, Screenwriter, Design Studio, Director, Music & Foley, and $O(V+E)$ Stage QA Critic) collaborate on a single Knowledge Graph.
          </p>
        </div>
      </div>
    </div>

    <form className="space-y-6">
      <ProductionFormatCard projectType={form.watch('type')} setValue={form.setValue} />
      <StoryConceptCard
        register={form.register}
        errors={form.formState.errors}
        conceptLength={(form.watch('base_concept') || '').length}
      />
      <DurationAndAspectGrid
        projectType={form.watch('type')}
        videoLength={form.watch('video_length')}
        orientation={form.watch('orientation')}
        setValue={form.setValue}
      />
      <ProjectCreativePresetsCard
        visualStylePreset={form.watch('visual_style_preset') || 'superhero_blockbuster'}
        colorPalettePreset={form.watch('color_palette_preset') || 'warm_golden_amber'}
        directorStylePreset={form.watch('director_style_preset') || 'wonder_humanist_blocking'}
        setValue={form.setValue}
      />
      <LanguageAndGateModeCard
        language={form.watch('language') || 'en-IN'}
        autoApproveGates={Boolean(form.watch('auto_approve_gates'))}
        setValue={form.setValue}
      />
      <div className="flex justify-end gap-3 pt-2">
        <Button
          onClick={onSubmit}
          icon={existingProject ? Play : Sparkles}
          className="w-full md:w-auto"
          disabled={isSubmitting}
        >
          {isSubmitting
            ? 'Launching Studio...'
            : existingProject
              ? 'Save & Open Agent Studio'
              : 'Launch Agent-First StoryGraph Studio'}
        </Button>
      </div>
    </form>
  </motion.div>
)

export const ProjectForm = () => {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const form = useForm<ProjectFormData>({
    resolver: zodResolver(projectSchema),
    defaultValues: DEFAULT_PROJECT_FORM_VALUES,
  })
  const { existingProject, isLoadingProject } = useLoadProjectIntoForm(id, form)
  const { isSubmitting, submitForm } = useSubmitProjectForm(id, existingProject)

  if (isLoadingProject) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading production...</p>
      </div>
    )
  }

  return (
    <ProjectFormView form={form} existingProject={existingProject} isSubmitting={isSubmitting} onSubmit={form.handleSubmit(submitForm)} onBack={() => navigate('/productions')} />
  )
}
