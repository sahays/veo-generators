import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Plus,
  Trash2,
  Film,
  Sparkles,
  CheckCircle2,
  Clock,
  GitBranch,
  Play,
  Sliders,
  Search,
  Layers,
  Eye,
  Monitor,
  Smartphone,
  DollarSign,
  Loader2,
} from 'lucide-react'
import { api } from '@/lib/api'
import type { Project } from '@/types/project'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Modal } from '@/components/Modal'
import { useAuthStore } from '@/store/useAuthStore'
import { cn } from '@/lib/utils'

const STAGE_LABELS: Record<string, string> = {
  S0_INGEST: 'S0 · Brief Ingested',
  S1_EXTRACT: 'S1 · World & Entities',
  S2_SCREENPLAY: 'S2 · Screenplay & Dialogue',
  S3_DESIGN: 'S3 · Visual Reference Sheets',
  S4_SHOTS: 'S4 · Director Shot List',
  S5_MUSIC: 'S5 · Music & SFX Cues',
  S6_VALIDATE: 'S6 · Validator V1–V13',
  S7_COMPILE: 'S7 · Prompt Compiler',
  S8_RENDER: 'S8 · Video Clip Render',
  S9_QA: 'S9 · Multimodal Clip QA',
  S10_ASSEMBLE: 'S10 · Master Final Cut',
}

export const ProjectList = () => {
  const navigate = useNavigate()
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'completed' | 'active'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const list = await api.projects.list()
        setProjects(list)
        if (list.length > 0) {
          setSelectedId(list[0].id)
        }
      } catch (err) {
        console.error('Failed to fetch productions', err)
      } finally {
        setIsLoading(false)
      }
    }
    fetchProjects()
  }, [])

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      await api.projects.delete(deleteTarget.id)
      const nextList = projects.filter((p) => p.id !== deleteTarget.id)
      setProjects(nextList)
      if (selectedId === deleteTarget.id) {
        setSelectedId(nextList[0]?.id ?? null)
      }
      setDeleteTarget(null)
    } catch (err) {
      console.error('Failed to delete production', err)
    } finally {
      setIsDeleting(false)
    }
  }

  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const isCompleted = p.status === 'completed' || !!p.final_video_url
      if (statusFilter === 'completed' && !isCompleted) return false
      if (statusFilter === 'active' && isCompleted) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchName = (p.name || '').toLowerCase().includes(q)
        const matchConcept = (p.base_concept || '').toLowerCase().includes(q)
        const matchId = p.id.toLowerCase().includes(q)
        return matchName || matchConcept || matchId
      }
      return true
    })
  }, [projects, statusFilter, searchQuery])

  const selectedProduction = useMemo(() => {
    return (
      filteredProjects.find((p) => p.id === selectedId) ||
      projects.find((p) => p.id === selectedId) ||
      filteredProjects[0] ||
      null
    )
  }, [filteredProjects, projects, selectedId])

  const completedCount = projects.filter(
    (p) => p.status === 'completed' || !!p.final_video_url,
  ).length
  const activeCount = projects.length - completedCount

  const getThumbnailUrl = (p: Project) =>
    (p as any).thumbnail_url || p.scenes?.[0]?.thumbnail_url || p.reference_image_url

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="w-full space-y-6 pb-20"
    >
      {/* FULL-WIDTH STUDIO HEADER */}
      <div className="glass rounded-2xl p-6 border border-border/80 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent-dark">
                <Film size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-2xl font-heading text-foreground tracking-tight">
                    Story-to-Video Productions Studio
                  </h2>
                  <span className="px-2.5 py-0.5 rounded-full bg-accent/15 text-accent-dark border border-accent/30 text-[10px] font-mono font-bold uppercase">
                    10-Stage StoryGraph Engine
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Multi-agent story extraction, canonical visual reference sheets, continuity
                  validation, and Gemini Omni / Veo video synthesis.
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-muted/50 border border-border text-xs font-mono">
              <span className="text-foreground font-bold">{projects.length} Total</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-emerald-400 font-bold">{completedCount} Master Cuts</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-amber-400 font-bold">{activeCount} In Progress</span>
            </div>

            {canWrite && (
              <Button icon={Plus} size="lg" onClick={() => navigate('/productions/new')}>
                New Story Production
              </Button>
            )}
          </div>
        </div>

        {/* SEARCH & FILTER BAR */}
        <div className="pt-4 border-t border-border/60 flex flex-wrap items-center justify-between gap-3">
          <div className="relative w-full sm:w-80">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search productions by title, story concept, or ID..."
              className="pl-9 h-9 text-xs bg-card border-border"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {[
              { id: 'all', label: `All Productions (${projects.length})`, icon: Layers },
              {
                id: 'completed',
                label: `Completed Final Cuts (${completedCount})`,
                icon: CheckCircle2,
              },
              { id: 'active', label: `In Pipeline (${activeCount})`, icon: Clock },
            ].map((tab) => (
              <Button
                key={tab.id}
                size="xs"
                variant={statusFilter === tab.id ? 'primary' : 'outline'}
                icon={tab.icon}
                onClick={() => setStatusFilter(tab.id as any)}
              >
                {tab.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <div key={n} className="glass rounded-2xl p-5 border border-border/60 space-y-4">
              <Skeleton className="w-full aspect-video rounded-xl" />
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
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
            <Button icon={Plus} size="lg" onClick={() => navigate('/productions/new')}>
              Create First Production
            </Button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
          {/* LEFT MAIN PANE: LARGE PRODUCTION CARDS GRID (8 Cols on XL) */}
          <div className="xl:col-span-8 grid grid-cols-1 md:grid-cols-2 gap-5">
            {filteredProjects.map((p) => {
              const isDone = p.status === 'completed' || !!p.final_video_url
              const isSelected = selectedProduction?.id === p.id
              const stageCode = p.current_stage || (isDone ? 'S10_ASSEMBLE' : 'S1_EXTRACT')
              const stageLabel = STAGE_LABELS[stageCode] || stageCode
              const thumbUrl = getThumbnailUrl(p)
              const dateValue = (p as any).timestamp || p.createdAt

              return (
                <div
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    'cursor-pointer rounded-2xl overflow-hidden border transition-all flex flex-col justify-between group',
                    isSelected
                      ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-xl'
                      : 'glass border-border/80 hover:border-accent/50',
                  )}
                >
                  <div>
                    {/* Media Header Preview */}
                    <div className="aspect-video bg-muted relative overflow-hidden">
                      {p.final_video_url ? (
                        <video
                          src={p.final_video_url}
                          className="w-full h-full object-cover"
                          muted
                          playsInline
                          preload="metadata"
                          onMouseOver={(e) => e.currentTarget.play().catch(() => {})}
                          onMouseOut={(e) => {
                            e.currentTarget.pause()
                            e.currentTarget.currentTime = 0
                          }}
                        />
                      ) : thumbUrl ? (
                        <img src={thumbUrl} alt={p.name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-muted-foreground bg-gradient-to-br from-muted/80 to-card">
                          <GitBranch size={28} className="text-accent-dark/70" />
                          <span className="text-[11px] font-mono">{stageLabel}</span>
                        </div>
                      )}

                      <div className="absolute top-3 left-3 flex flex-wrap items-center gap-1.5">
                        <span
                          className={cn(
                            'px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase backdrop-blur-md flex items-center gap-1',
                            isDone
                              ? 'bg-emerald-500/90 text-white'
                              : 'bg-amber-500/90 text-black',
                          )}
                        >
                          {isDone ? <CheckCircle2 size={11} /> : <Clock size={11} />}
                          {isDone ? 'Master Cut Ready' : 'In Pipeline'}
                        </span>
                        <span className="px-2 py-0.5 rounded-full bg-black/75 text-white text-[10px] font-mono backdrop-blur-md">
                          {stageLabel}
                        </span>
                      </div>

                      {canWrite && (
                        <div
                          className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Button
                            variant="destructive"
                            size="icon"
                            onClick={() => setDeleteTarget(p)}
                            className="h-7 w-7 rounded-lg"
                            title="Delete Production"
                          >
                            <Trash2 size={13} />
                          </Button>
                        </div>
                      )}
                    </div>

                    {/* Card Content */}
                    <div className="p-5 space-y-3">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h4 className="font-heading text-base font-bold text-foreground group-hover:text-accent-dark transition-colors">
                            {p.name || 'Untitled Production'}
                          </h4>
                          <span className="text-[10px] font-mono text-muted-foreground">
                            ID: {p.id} ·{' '}
                            {dateValue ? new Date(dateValue).toLocaleDateString() : 'Recent'}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground shrink-0">
                          <span className="px-2 py-0.5 rounded bg-muted border border-border/60">
                            {p.orientation || '16:9'}
                          </span>
                          <span className="px-2 py-0.5 rounded bg-muted border border-border/60">
                            {p.video_length || '32'}s
                          </span>
                        </div>
                      </div>

                      <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                        {p.base_concept || 'Story-to-Video multi-agent pipeline production.'}
                      </p>
                    </div>
                  </div>

                  {/* Card Footer Actions */}
                  <div
                    className="px-5 pb-4 pt-3 border-t border-border/50 flex items-center justify-between gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Button
                      size="xs"
                      variant="primary"
                      icon={GitBranch}
                      onClick={() => navigate(`/productions/${p.id}/script`)}
                    >
                      Open StoryGraph Studio
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      icon={Eye}
                      onClick={() => navigate(`/productions/${p.id}`)}
                    >
                      Summary
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>

          {/* RIGHT STICKY DETAILS & QUICK INSPECTOR PANE (4 Cols on XL) */}
          <div className="xl:col-span-4 xl:sticky xl:top-4">
            {selectedProduction ? (
              <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
                <div className="flex items-center justify-between border-b border-border/60 pb-3">
                  <div className="flex items-center gap-2">
                    <Sliders size={16} className="text-accent-dark" />
                    <h3 className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
                      Production Inspector
                    </h3>
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {selectedProduction.id}
                  </span>
                </div>

                {/* Video or Image Preview */}
                <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border">
                  {selectedProduction.final_video_url ? (
                    <video
                      key={selectedProduction.final_video_url}
                      controls
                      preload="metadata"
                      src={selectedProduction.final_video_url}
                      className="w-full h-full"
                    />
                  ) : getThumbnailUrl(selectedProduction) ? (
                    <img
                      src={getThumbnailUrl(selectedProduction)}
                      alt={selectedProduction.name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-muted-foreground">
                      <Play size={24} className="text-accent-dark" />
                      <span className="text-xs">Open Studio to run pipeline</span>
                    </div>
                  )}
                </div>

                {/* Title & Concept */}
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-lg font-heading font-bold text-foreground">
                      {selectedProduction.name}
                    </h4>
                    <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
                      {STAGE_LABELS[selectedProduction.current_stage || ''] ||
                        selectedProduction.status ||
                        'Active'}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto pr-1">
                    {selectedProduction.base_concept || 'No concept description provided.'}
                  </p>
                </div>

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 gap-2.5 text-xs">
                  <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 flex items-center gap-2">
                    {selectedProduction.orientation === '9:16' ? (
                      <Smartphone size={14} className="text-accent-dark" />
                    ) : (
                      <Monitor size={14} className="text-accent-dark" />
                    )}
                    <div>
                      <span className="text-[9px] font-mono uppercase text-muted-foreground block">
                        Aspect Ratio
                      </span>
                      <span className="font-mono font-bold">
                        {selectedProduction.orientation || '16:9'}
                      </span>
                    </div>
                  </div>
                  <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 flex items-center gap-2">
                    <Clock size={14} className="text-accent-dark" />
                    <div>
                      <span className="text-[9px] font-mono uppercase text-muted-foreground block">
                        Target Duration
                      </span>
                      <span className="font-mono font-bold">
                        {selectedProduction.video_length || '32'}s
                      </span>
                    </div>
                  </div>
                  {(selectedProduction as any).estimated_cost !== undefined && (
                    <div className="col-span-2 p-2.5 rounded-lg bg-muted/40 border border-border/60 flex items-center justify-between">
                      <span className="text-[10px] font-mono uppercase text-muted-foreground flex items-center gap-1">
                        <DollarSign size={12} className="text-emerald-400" /> Estimated Pipeline
                        Cost
                      </span>
                      <span className="font-mono font-bold text-emerald-400">
                        ${Number((selectedProduction as any).estimated_cost || 0).toFixed(4)}
                      </span>
                    </div>
                  )}
                </div>

                {/* Primary Studio Actions */}
                <div className="space-y-2 pt-2 border-t border-border/60">
                  <Button
                    variant="primary"
                    size="lg"
                    icon={GitBranch}
                    onClick={() => navigate(`/productions/${selectedProduction.id}/script`)}
                    className="w-full"
                  >
                    Launch StoryGraph Studio (S1–S10)
                  </Button>
                  <div className="grid grid-cols-2 gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      icon={Eye}
                      onClick={() => navigate(`/productions/${selectedProduction.id}`)}
                    >
                      View Summary
                    </Button>
                    {canWrite && (
                      <Button
                        variant="outline"
                        size="sm"
                        icon={Sliders}
                        onClick={() => navigate(`/productions/${selectedProduction.id}/edit`)}
                      >
                        Edit Story Brief
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      <Modal
        isOpen={!!deleteTarget}
        onClose={() => !isDeleting && setDeleteTarget(null)}
        title="Delete Production"
        subtitle="This action will archive and remove this production from your active studio workspace."
        maxWidth="max-w-md"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)} disabled={isDeleting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              icon={isDeleting ? Loader2 : Trash2}
              onClick={confirmDelete}
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
    </motion.div>
  )
}
