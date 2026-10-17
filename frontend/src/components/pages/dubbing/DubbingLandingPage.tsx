import { Film, Languages } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/hooks/useApiClient'
import { UNIFIED_STATUS_LABELS } from '@/hooks/jobStatus'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard } from '@/components/shared/RecordCard'

interface DubVariant {
  language_code: string
  status: string
  output_signed_url?: string
}

interface DubRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  duration_sec?: number
  variants?: DubVariant[]
  source_signed_url?: string
  usage?: { cost_usd?: number }
  createdAt: string
  completedAt?: string
}

const DUB_STATUS_LABELS: Record<string, string> = {
  ...UNIFIED_STATUS_LABELS,
  generating: 'Dubbing',
}

const VARIANT_DOT: Record<string, string> = {
  completed: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/25',
  failed: 'bg-red-500/15 text-red-600 border-red-500/25',
  generating: 'bg-blue-500/15 text-blue-600 border-blue-500/25',
  pending: 'bg-slate-500/15 text-slate-600 border-slate-500/25',
}

export const DubbingLandingPage = () => (
  <LandingPageShell<DubRecord>
    title="Dubbing"
    subtitle="Dub a video into Spanish, Portuguese, German or Hindi with Gemini Live Translate"
    icon={Languages}
    fetchRecords={() => api.dubbing.list()}
    archiveRecord={(id) => api.dubbing.archive(id)}
    createPath="/dubbing/create"
    detailPath="/dubbing"
    buttonLabel="New Dub"
    renderCard={(record, onClick, onArchive, showArchive) => {
      const preview =
        record.variants?.find((v) => v.status === 'completed')?.output_signed_url ||
        record.source_signed_url

      return (
        <RecordCard
          key={record.id}
          onClick={onClick}
          title={record.display_name || record.source_filename || 'Untitled video'}
          status={record.status}
          statusIcon={Languages}
          statusLabels={DUB_STATUS_LABELS}
          progressPct={record.progress_pct}
          activeStatuses={['generating']}
          badges={record.variants?.map((v) => (
            <span
              key={v.language_code}
              className={cn(
                'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border',
                VARIANT_DOT[v.status] || VARIANT_DOT.pending,
              )}
            >
              {v.language_code}
            </span>
          ))}
          sideMedia={
            <div className="w-24 shrink-0 aspect-video rounded-lg overflow-hidden bg-muted border border-border/50 flex items-center justify-center">
              {preview ? (
                <video
                  src={`${preview}#t=0.1`}
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
            durationSec: record.duration_sec,
            costUsd: record.usage?.cost_usd,
            showArchive,
            onArchive,
          }}
        />
      )
    }}
    emptyTitle="No dubs yet"
    emptyDescription="Pick a video with spoken audio and choose target languages. Each language comes back as its own dubbed video with a transcript and subtitles."
  />
)
