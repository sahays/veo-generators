import {
  Plus,
  Trash2,
  Film,
  CheckCircle2,
  Clock,
  GitBranch,
  Sliders,
  Search,
  Layers,
  Eye,
} from 'lucide-react'
import type { Project } from '@/types/project'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export const STAGE_LABELS: Record<string, string> = {
  S0_INGEST: 'S0 · Brief Ingested',
  S1_EXTRACT: 'S1 · World & Entities',
  S2_SCREENPLAY: 'S2 · Screenplay & Dialogue',
  S3_DESIGN: 'S3 · Visual Reference Sheets',
  S4_SHOTS: 'S4 · Director Shot List',
  S5_MUSIC: 'S5 · Music & SFX Cues',
  S6_VALIDATE: 'S6 · Validator V1–V13',
  S7_COMPILE: 'S7 · Prompt Compiler',
  S8_KEYFRAMES: 'S8K · 1 fps Keyframes',
  S8_RENDER: 'S8 · Video Clip Render',
  S9_QA: 'S9 · Multimodal Clip QA',
  S10_ASSEMBLE: 'S10 · Master Final Cut',
}

export type ProjectStatusFilter = 'all' | 'completed' | 'active'

export interface ExtendedProject extends Project {
  thumbnail_url?: string
  timestamp?: string
  estimated_cost?: number
}

export const getProjectThumbnailUrl = (p: ExtendedProject): string | undefined =>
  p.thumbnail_url || p.scenes?.[0]?.thumbnail_url || p.reference_image_url

export const ProjectListHeader = ({
  totalCount,
  completedCount,
  activeCount,
  canWrite,
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  onNewProduction,
}: {
  totalCount: number
  completedCount: number
  activeCount: number
  canWrite: boolean
  searchQuery: string
  onSearchChange: (q: string) => void
  statusFilter: ProjectStatusFilter
  onStatusFilterChange: (f: ProjectStatusFilter) => void
  onNewProduction: () => void
}) => (
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
          <span className="text-foreground font-bold">{totalCount} Total</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-emerald-400 font-bold">{completedCount} Master Cuts</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-amber-400 font-bold">{activeCount} In Progress</span>
        </div>

        {canWrite && (
          <Button icon={Plus} size="lg" onClick={onNewProduction}>
            New Story Production
          </Button>
        )}
      </div>
    </div>

    <div className="pt-4 border-t border-border/60 flex flex-wrap items-center justify-between gap-3">
      <div className="relative w-full sm:w-80">
        <Search
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
        />
        <Input
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search productions by title, story concept, or ID..."
          className="pl-9 h-9 text-xs bg-card border-border"
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            { id: 'all', label: `All Productions (${totalCount})`, icon: Layers },
            { id: 'completed', label: `Completed Final Cuts (${completedCount})`, icon: CheckCircle2 },
            { id: 'active', label: `In Pipeline (${activeCount})`, icon: Clock },
          ] as const
        ).map((tab) => (
          <Button
            key={tab.id}
            size="xs"
            variant={statusFilter === tab.id ? 'primary' : 'outline'}
            icon={tab.icon}
            onClick={() => onStatusFilterChange(tab.id)}
          >
            {tab.label}
          </Button>
        ))}
      </div>
    </div>
  </div>
)

export const ProjectCardItem = ({
  project,
  canWrite,
  onDelete,
  onOpenStudio,
  onOpenSummary,
  onEdit,
}: {
  project: ExtendedProject
  canWrite: boolean
  onDelete: () => void
  onOpenStudio: () => void
  onOpenSummary: () => void
  onEdit?: () => void
}) => {
  const isDone = project.status === 'completed' || !!project.final_video_url
  const stageCode = project.current_stage || (isDone ? 'S10_ASSEMBLE' : 'S1_EXTRACT')
  const stageLabel = STAGE_LABELS[stageCode] || stageCode
  const thumbUrl = getProjectThumbnailUrl(project)
  const dateValue = project.timestamp || project.createdAt

  return (
    <div
      onClick={onOpenStudio}
      className="cursor-pointer rounded-2xl overflow-hidden border glass border-border/80 hover:border-accent/50 transition-all flex flex-col justify-between group"
    >
      <div>
        <div className="aspect-video bg-muted relative overflow-hidden">
          {project.final_video_url ? (
            <video
              src={project.final_video_url}
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
            <img src={thumbUrl} alt={project.name} className="w-full h-full object-cover" />
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
                isDone ? 'bg-emerald-500/90 text-white' : 'bg-amber-500/90 text-black',
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
                onClick={onDelete}
                className="h-7 w-7 rounded-lg"
                title="Archive Production"
              >
                <Trash2 size={13} />
              </Button>
            </div>
          )}
        </div>

        <div className="p-5 space-y-3">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h4 className="font-heading text-base font-bold text-foreground group-hover:text-accent-dark transition-colors">
                {project.name || 'Untitled Production'}
              </h4>
              <span className="text-[10px] font-mono text-muted-foreground">
                ID: {project.id} · {dateValue ? new Date(dateValue).toLocaleDateString() : 'Recent'}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[10px] font-mono text-muted-foreground shrink-0">
              <span className="px-2 py-0.5 rounded bg-muted border border-border/60">
                {project.orientation || '16:9'}
              </span>
              <span className="px-2 py-0.5 rounded bg-muted border border-border/60">
                {project.video_length || '32'}s
              </span>
            </div>
          </div>

          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
            {project.base_concept || 'Story-to-Video multi-agent pipeline production.'}
          </p>
        </div>
      </div>

      <div
        className="px-5 pb-4 pt-3 border-t border-border/50 flex items-center justify-between gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        <Button size="xs" variant="primary" icon={GitBranch} onClick={onOpenStudio}>
          Open StoryGraph Studio
        </Button>
        <div className="flex items-center gap-1.5">
          {canWrite && onEdit && (
            <Button size="xs" variant="outline" icon={Sliders} onClick={onEdit}>
              Edit
            </Button>
          )}
          <Button size="xs" variant="outline" icon={Eye} onClick={onOpenSummary}>
            Summary
          </Button>
        </div>
      </div>
    </div>
  )
}
