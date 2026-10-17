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
          form.reset({
            name: project.name,
            type: project.type || 'movie',
            base_concept: project.base_concept,
            video_length: String(project.video_length || '16') as ProjectFormData['video_length'],
            orientation: project.orientation || '16:9',
            language: project.language || 'en-IN',
            auto_approve_gates: Boolean(project.auto_approve_gates),
          })
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
      const payload: Partial<Project> = {
        name: data.name,
        type: data.type,
        base_concept: data.base_concept,
        video_length: data.video_length as Project['video_length'],
        orientation: data.orientation,
        language: data.language,
        auto_approve_gates: Boolean(data.auto_approve_gates),
      }
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
    className="space-y-6 max-w-3xl mx-auto pb-20"
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
      <ProductionFormatCard projectType={form.watch('type')} setValue={form.setValue} />
      <StoryConceptCard
        register={form.register}
        errors={form.formState.errors}
        conceptLength={(form.watch('base_concept') || '').length}
      />
      <DurationAndAspectGrid
        videoLength={form.watch('video_length')}
        orientation={form.watch('orientation')}
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
              ? 'Save & Open StoryGraph Studio'
              : 'Launch Story-to-Video Graph Studio'}
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
    defaultValues: { name: '', type: 'movie', base_concept: '', video_length: '16', orientation: '16:9', language: 'en-IN', auto_approve_gates: false },
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
