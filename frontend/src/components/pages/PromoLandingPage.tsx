import { Scissors } from 'lucide-react'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard } from '@/components/shared/RecordCard'

interface PromoRecord {
  id: string
  source_filename: string
  display_name?: string
  status: string
  progress_pct: number
  usage?: { cost_usd?: number }
  prompt_name?: string
  createdAt: string
  completedAt?: string
}

export const PromoLandingPage = () => (
  <LandingPageShell<PromoRecord>
    title="Promos"
    subtitle="AI-powered promotional clips from your full-length videos"
    icon={Scissors}
    fetchRecords={() => api.promo.list()}
    archiveRecord={(id) => api.promo.archive(id)}
    createPath="/promos/create"
    detailPath="/promos"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <RecordCard
        key={record.id}
        onClick={onClick}
        title={record.display_name || record.source_filename || 'Untitled video'}
        status={record.status}
        statusIcon={Scissors}
        progressPct={record.progress_pct}
        activeStatuses={['analyzing', 'extracting', 'stitching', 'encoding']}
        footerProps={{
          createdAt: record.createdAt,
          completedAt: record.completedAt,
          costUsd: record.usage?.cost_usd,
          showArchive,
          onArchive,
        }}
      >
        {record.prompt_name && (
          <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-medium bg-amber-500/10 text-amber-600 mb-2">
            {record.prompt_name}
          </span>
        )}
      </RecordCard>
    )}
    emptyTitle="No promos yet"
    emptyDescription="Select a video to generate a promotional highlight reel of the best moments."
  />
)
