import { Smartphone, Film } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard } from '@/components/shared/RecordCard'

interface ReframeRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  content_type?: string
  blurred_bg?: boolean
  diagnostic_mode?: boolean
  output_aspect_ratio?: string
  source_signed_url?: string
  output_signed_url?: string
  usage?: { cost_usd?: number }
  createdAt: string
  completedAt?: string
}

export const ReframeLandingPage = () => (
  <LandingPageShell<ReframeRecord>
    title="Orientations"
    subtitle="Smart reframe 16:9 videos to 9:16 or 3:4 with AI subject tracking"
    icon={Smartphone}
    fetchRecords={() => api.reframe.list()}
    archiveRecord={(id) => api.reframe.archive(id)}
    createPath="/orientations/create"
    detailPath="/orientations"
    buttonLabel="New Reframe"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <RecordCard
        key={record.id}
        onClick={onClick}
        title={record.display_name || record.source_filename || 'Untitled video'}
        status={record.status}
        statusIcon={Smartphone}
        progressPct={record.progress_pct}
        activeStatuses={['analyzing', 'processing', 'encoding']}
        badges={
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border',
              record.diagnostic_mode
                ? 'bg-amber-500/10 text-amber-600 border-amber-500/20'
                : 'bg-slate-500/10 text-slate-600 border-slate-500/20',
            )}
          >
            {record.diagnostic_mode
              ? 'Diagnostic'
              : record.output_aspect_ratio === '3:4'
                ? 'Adaptive 3:4'
                : 'Adaptive 9:16'}
          </span>
        }
        sideMedia={
          <div
            className={cn(
              'w-16 shrink-0 rounded-lg overflow-hidden bg-muted border border-border/50 flex items-center justify-center',
              record.output_aspect_ratio === '3:4' ? 'aspect-[3/4]' : 'aspect-[9/16]',
            )}
          >
            {record.output_signed_url ? (
              <video
                src={`${record.output_signed_url}#t=0.1`}
                muted
                playsInline
                preload="metadata"
                className="w-full h-full object-cover"
              />
            ) : (
              <Film size={16} className="text-muted-foreground/40" />
            )}
          </div>
        }
        footerProps={{
          createdAt: record.createdAt,
          completedAt: record.completedAt,
          costUsd: record.usage?.cost_usd,
          showArchive,
          onArchive,
        }}
      />
    )}
    emptyTitle="No reframes yet"
    emptyDescription="Select a landscape video to intelligently reframe it to 9:16 or 3:4 portrait using AI subject tracking."
  />
)
