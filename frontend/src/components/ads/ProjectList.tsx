import { motion } from 'framer-motion'
import { Plus, FolderOpen, Clock, Loader2, CheckCircle2, AlertCircle, Image as ImageIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { SEED_PROJECTS } from '@/lib/mockData'
import type { Project } from '@/types/project'
import { useNavigate } from 'react-router-dom'

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: any }> = {
  draft: { label: 'Draft', color: 'text-muted-foreground bg-muted', icon: Clock },
  analyzing: { label: 'Analyzing', color: 'text-blue-600 bg-blue-500/10', icon: Loader2 },
  scripted: { label: 'Scripted', color: 'text-indigo-600 bg-indigo-500/10', icon: CheckCircle2 },
  generating: { label: 'Generating', color: 'text-amber-600 bg-amber-500/10', icon: Loader2 },
  completed: { label: 'Completed', color: 'text-emerald-600 bg-emerald-500/10', icon: CheckCircle2 },
  failed: { label: 'Failed', color: 'text-red-500 bg-red-500/10', icon: AlertCircle },
}

const ProjectCard = ({ project, onClick }: { project: Project; onClick: () => void }) => {
  const config = STATUS_CONFIG[project.status] || STATUS_CONFIG.draft
  const StatusIcon = config.icon
  const timeAgo = getTimeAgo(project.updatedAt)

  const typeLabels: Record<string, string> = {
    movie: 'Movie',
    advertizement: 'Ad',
    social: 'Social'
  }

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-5 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark text-[9px] font-bold uppercase tracking-wider border border-accent/20">
              {typeLabels[project.type] || project.type}
            </span>
            <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1">
              {project.name}
            </h4>
          </div>
        </div>
        <div className={cn("flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0", config.color)}>
          <StatusIcon size={10} className={project.status === 'generating' || project.status === 'analyzing' ? 'animate-spin' : ''} />
          {config.label}
        </div>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 mb-4 leading-relaxed">
        {project.base_concept}
      </p>

      {/* Storyboard Preview */}
      {project.scenes.length > 0 && (
        <div className="flex gap-2 mb-4 overflow-hidden">
          {project.scenes.slice(0, 4).map((scene) => (
            <div 
              key={scene.id} 
              className="relative aspect-video w-20 shrink-0 rounded-md overflow-hidden bg-muted border border-border/50"
            >
              {scene.thumbnail_url ? (
                <img src={scene.thumbnail_url} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <ImageIcon size={12} className="text-muted-foreground/40" />
                </div>
              )}
            </div>
          ))}
          {project.scenes.length > 4 && (
            <div className="aspect-video w-10 shrink-0 rounded-md bg-accent/10 flex items-center justify-center text-[10px] font-bold text-accent-dark border border-accent/20">
              +{project.scenes.length - 4}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{project.video_length}s · {project.orientation}</span>
        <span>{timeAgo}</span>
      </div>
    </motion.button>
  )
}

export const ProjectList = () => {
  const { setActiveProject, projects } = useProjectStore()
  const navigate = useNavigate()
  
  // Use projects from store which is initialized with SEED_PROJECTS
  const displayProjects = projects.length > 0 ? projects : SEED_PROJECTS

  const handleNewProject = () => {
    setActiveProject(null)
    navigate('/productions/new')
  }

  const handleOpenProject = (id: string) => {
    setActiveProject(id)
    const project = displayProjects.find(p => p.id === id)
    if (project?.status === 'completed') {
      navigate(`/productions/${id}`)
    } else if (project?.status === 'scripted' || project?.status === 'generating') {
      navigate(`/productions/${id}/script`)
    } else {
      navigate(`/productions/${id}/edit`)
    }
  }

  const projectsCount = displayProjects.length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Productions</h2>
          <p className="text-xs text-muted-foreground">
            {projectsCount} project{projectsCount !== 1 ? 's' : ''}
          </p>
        </div>
        <Button icon={Plus} onClick={handleNewProject}>New Production</Button>
      </div>

      {projectsCount === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="glass bg-card rounded-xl p-12 flex flex-col items-center justify-center text-center"
        >
          <div className="w-14 h-14 rounded-full bg-accent/20 text-accent-dark flex items-center justify-center mb-4">
            <FolderOpen size={28} />
          </div>
          <h4 className="text-base font-heading font-bold text-foreground mb-1">No projects yet</h4>
          <p className="text-sm text-muted-foreground max-w-xs mb-5">
            Create your first ad generation project to get started.
          </p>
          <Button icon={Plus} onClick={handleNewProject}>Create First Production</Button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {displayProjects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onClick={() => handleOpenProject(project.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function getTimeAgo(timestamp: number): string {
  const diff = Date.now() - timestamp
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'Just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
