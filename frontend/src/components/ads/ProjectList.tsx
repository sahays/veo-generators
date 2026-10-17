import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Plus, Trash2, Sparkles, Loader2 } from 'lucide-react'
import { Button } from '@/components/Common'
import { Skeleton } from '@/components/ui/skeleton'
import { Modal } from '@/components/Modal'
import { useAuthStore } from '@/store/useAuthStore'
import { useAdsProjectActions } from './projects/useAdsProjectActions'
import {
  ProjectListHeader,
  ProjectCardItem,
  ProductionInspectorPanel,
  type ExtendedProject,
  type ProjectStatusFilter,
} from './projects/ProjectListSubcomponents'

function filterProjectList(
  projects: ExtendedProject[],
  statusFilter: ProjectStatusFilter,
  searchQuery: string,
): ExtendedProject[] {
  return projects.filter((p) => {
    const isCompleted = p.status === 'completed' || !!p.final_video_url
    if (statusFilter === 'completed' && !isCompleted) return false
    if (statusFilter === 'active' && isCompleted) return false
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      return (
        (p.name || '').toLowerCase().includes(q) ||
        (p.base_concept || '').toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q)
      )
    }
    return true
  })
}

const EmptyProductionsCard = ({
  canWrite,
  onNewProduction,
}: {
  canWrite: boolean
  onNewProduction: () => void
}) => (
  <div className="glass rounded-2xl p-12 border border-border/80 text-center space-y-4">
    <Sparkles size={32} className="mx-auto text-accent-dark" />
    <div className="space-y-1">
      <h3 className="text-lg font-heading font-bold text-foreground">No productions yet</h3>
      <p className="text-xs text-muted-foreground max-w-md mx-auto">
        Create your first Story-to-Video Graph production to extract characters, design
        reference sheets, and render multi-shot cinema.
      </p>
    </div>
    {canWrite && (
      <Button icon={Plus} size="lg" onClick={onNewProduction}>
        Create First Production
      </Button>
    )}
  </div>
)

function useProjectListData() {
  const { projects: projectsApi } = useAdsProjectActions()
  const [projects, setProjects] = useState<ExtendedProject[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<ExtendedProject | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    projectsApi
      .list()
      .then((list) => {
        setProjects(list)
        if (list.length > 0) setSelectedId(list[0].id)
      })
      .catch(() => null)
      .finally(() => setIsLoading(false))
  }, [projectsApi])

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      await projectsApi.delete(deleteTarget.id)
      const nextList = projects.filter((p) => p.id !== deleteTarget.id)
      setProjects(nextList)
      if (selectedId === deleteTarget.id) setSelectedId(nextList[0]?.id ?? null)
      setDeleteTarget(null)
    } finally {
      setIsDeleting(false)
    }
  }

  return { projects, isLoading, deleteTarget, setDeleteTarget, isDeleting, selectedId, setSelectedId, confirmDelete }
}

const ProjectListBody = ({
  isLoading,
  projectsCount,
  filteredProjects,
  selectedProduction,
  canWrite,
  onSelect,
  onDelete,
  onNavigate,
}: {
  isLoading: boolean
  projectsCount: number
  filteredProjects: ExtendedProject[]
  selectedProduction: ExtendedProject | null
  canWrite: boolean
  onSelect: (id: string) => void
  onDelete: (p: ExtendedProject) => void
  onNavigate: (path: string) => void
}) =>
  isLoading ? (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
      {[1, 2, 3, 4, 5, 6].map((n) => (
        <div key={n} className="glass rounded-2xl p-5 border border-border/60 space-y-4">
          <Skeleton className="w-full aspect-video rounded-xl" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  ) : projectsCount === 0 ? (
    <EmptyProductionsCard canWrite={canWrite} onNewProduction={() => onNavigate('/productions/new')} />
  ) : (
    <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
      <div className="xl:col-span-8 grid grid-cols-1 md:grid-cols-2 gap-5">
        {filteredProjects.map((p) => (
          <ProjectCardItem
            key={p.id}
            project={p}
            isSelected={selectedProduction?.id === p.id}
            canWrite={canWrite}
            onSelect={() => onSelect(p.id)}
            onDelete={() => onDelete(p)}
            onOpenStudio={() => onNavigate(`/productions/${p.id}/script`)}
            onOpenSummary={() => onNavigate(`/productions/${p.id}`)}
          />
        ))}
      </div>
      <div className="xl:col-span-4 xl:sticky xl:top-4">
        {selectedProduction && (
          <ProductionInspectorPanel
            production={selectedProduction}
            canWrite={canWrite}
            onNavigate={onNavigate}
          />
        )}
      </div>
    </div>
  )

const DeleteProductionModal = ({
  deleteTarget,
  isDeleting,
  onClose,
  onConfirm,
}: {
  deleteTarget: ExtendedProject | null
  isDeleting: boolean
  onClose: () => void
  onConfirm: () => void
}) => (
  <Modal
    isOpen={!!deleteTarget}
    onClose={() => !isDeleting && onClose()}
    title="Delete Production"
    subtitle="This action will archive and remove this production from your active studio workspace."
    maxWidth="max-w-md"
    footer={
      <>
        <Button variant="ghost" onClick={onClose} disabled={isDeleting}>
          Cancel
        </Button>
        <Button
          variant="destructive"
          icon={isDeleting ? Loader2 : Trash2}
          onClick={onConfirm}
          disabled={isDeleting}
        >
          {isDeleting ? 'Deleting...' : 'Delete Production'}
        </Button>
      </>
    }
  >
    <p className="text-sm text-muted-foreground">
      Are you sure you want to delete{' '}
      <strong className="text-foreground">{deleteTarget?.name || deleteTarget?.id}</strong>?
    </p>
  </Modal>
)

export const ProjectList = () => {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<ProjectStatusFilter>('all')
  const data = useProjectListData()
  const filteredProjects = useMemo(() => filterProjectList(data.projects, statusFilter, searchQuery), [data.projects, statusFilter, searchQuery])
  const selectedProduction = useMemo(
    () => filteredProjects.find((p) => p.id === data.selectedId) || data.projects.find((p) => p.id === data.selectedId) || filteredProjects[0] || null,
    [filteredProjects, data.projects, data.selectedId],
  )
  const completedCount = data.projects.filter((p) => p.status === 'completed' || !!p.final_video_url).length

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} className="w-full space-y-6 pb-20">
      <ProjectListHeader
        totalCount={data.projects.length} completedCount={completedCount} activeCount={data.projects.length - completedCount}
        canWrite={canWrite} searchQuery={searchQuery} onSearchChange={setSearchQuery} statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter} onNewProduction={() => navigate('/productions/new')}
      />
      <ProjectListBody
        isLoading={data.isLoading} projectsCount={data.projects.length} filteredProjects={filteredProjects} selectedProduction={selectedProduction}
        canWrite={canWrite} onSelect={data.setSelectedId} onDelete={data.setDeleteTarget} onNavigate={navigate}
      />
      <DeleteProductionModal deleteTarget={data.deleteTarget} isDeleting={data.isDeleting} onClose={() => data.setDeleteTarget(null)} onConfirm={data.confirmDelete} />
    </motion.div>
  )
}
