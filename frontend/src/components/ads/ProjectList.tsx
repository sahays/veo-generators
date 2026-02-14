import { motion } from 'framer-motion'
import { Plus, FolderOpen, Clock, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import type { Project, ProjectStatus } from '@/types/project'

const STATUS_CONFIG: Record<ProjectStatus, { label: string; color: string; icon: typeof Clock }> = {
  draft: { label: 'Draft', color: 'text-muted-foreground bg-muted', icon: Clock },
  generating: { label: 'Generating', color: 'text-amber-600 bg-amber-500/10', icon: Loader2 },
  completed: { label: 'Completed', color: 'text-emerald-600 bg-emerald-500/10', icon: CheckCircle2 },
  failed: { label: 'Failed', color: 'text-red-500 bg-red-500/10', icon: AlertCircle },
}

const ProjectCard = ({ project, onClick }: { project: Project; onClick: () => void }) => {
  const config = STATUS_CONFIG[project.status]
  const StatusIcon = config.icon
  const timeAgo = getTimeAgo(project.updatedAt)

  return (
    <motion.button
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="glass bg-card p-5 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
    >
      <div className="flex items-start justify-between mb-3">
        <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1">
          {project.name}
        </h4>
        <div className={cn("flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0", config.color)}>
          <StatusIcon size={10} className={project.status === 'generating' ? 'animate-spin' : ''} />
          {config.label}
        </div>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 mb-3 leading-relaxed">
        {project.prompt}
      </p>
      <div className="flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{project.videoLength}s · {project.directorStyle || 'No style'}</span>
        <span>{timeAgo}</span>
      </div>
    </motion.button>
  )
}

export const ProjectList = () => {
  const { projects, setView, setActiveProject } = useProjectStore()

  const handleNewProject = () => {
    setActiveProject(null)
    setView('form')
  }

  const handleOpenProject = (id: string) => {
    setActiveProject(id)
    setView('form')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">Projects</h2>
          <p className="text-xs text-muted-foreground">
            {projects.length} project{projects.length !== 1 ? 's' : ''}
          </p>
        </div>
        <Button icon={Plus} onClick={handleNewProject}>New Project</Button>
      </div>

      {projects.length === 0 ? (
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
          <Button icon={Plus} onClick={handleNewProject}>Create First Project</Button>
        </motion.div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((project) => (
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
