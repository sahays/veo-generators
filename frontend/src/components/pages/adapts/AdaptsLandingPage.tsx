import { LayoutGrid } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard } from '@/components/shared/RecordCard'
import type { AdaptRecord } from '@/types/project'

export const AdaptsLandingPage = () => (
  <LandingPageShell<AdaptRecord>
    title="Adapts"
    subtitle="Generate image variants across multiple aspect ratios for different devices and platforms"
    icon={LayoutGrid}
    fetchRecords={() => api.adapts.list()}
    archiveRecord={(id) => api.adapts.archive(id)}
    createPath="/adapts/create"
    detailPath="/adapts"
    renderCard={(record, onClick, onArchive, showArchive) => {
      const completedCount = record.variants.filter(
        (v) => v.status === 'completed',
      ).length
      return (
        <RecordCard
          key={record.id}
          onClick={onClick}
          title={record.display_name || record.source_filename || 'Untitled adapt'}
          status={record.status}
          statusIcon={LayoutGrid}
          progressPct={record.progress_pct}
          activeStatuses={['generating']}
          titleRight={
            <span className="text-[9px] text-muted-foreground">
              {completedCount}/{record.variants.length} variants
            </span>
          }
          topMedia={
            record.source_signed_url ? (
              <div className="aspect-video bg-muted/50 overflow-hidden">
                <img
                  src={record.source_signed_url}
                  alt={record.display_name || record.source_filename}
                  className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                />
              </div>
            ) : undefined
          }
          footerProps={{
            createdAt: record.createdAt,
            completedAt: record.completedAt,
            costUsd: record.usage?.cost_usd,
            showArchive,
            onArchive,
          }}
        >
          {record.preset_bundle && (
            <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-medium bg-amber-500/10 text-amber-600 mb-2 capitalize">
              {record.preset_bundle}
            </span>
          )}
        </RecordCard>
      )
    }}
    emptyTitle="No adapts yet"
    emptyDescription="Select an image to generate adapted versions for multiple aspect ratios and form factors."
  />
)
