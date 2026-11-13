import { TrendingUp } from 'lucide-react'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard, VideoSourceBadge } from '@/components/shared/RecordCard'
import { DurationPill } from '@/components/shared/timeline'
import { api } from '@/hooks/useApiClient'
import { engagementRecordName, signalBadgeText } from '@/types/engagement/reportFormat'
import type { EngagementRecord } from '@/types/insights'
import { SignalBadge } from './SignalBadge'
import { useTemplateLabels } from './useEngagementTemplates'

const ACTIVE_STATUSES = ['pending', 'processing']
const NO_HEADLINE = 'No headline was written for this report.'

interface EngagementCardProps {
  record: EngagementRecord
  templateLabels: ReadonlyMap<string, string>
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}

/** The headline of a finished report; nothing while the job is still running or failed. */
function cardDescription(record: EngagementRecord): string | undefined {
  if (record.status !== 'completed') return undefined
  return record.headline || NO_HEADLINE
}

const EngagementCard = ({ record, templateLabels, onClick, onArchive, showArchive }: EngagementCardProps) => (
  <RecordCard
    onClick={onClick}
    title={engagementRecordName(record)}
    description={cardDescription(record)}
    status={record.status}
    statusIcon={TrendingUp}
    progressPct={record.progress_pct}
    activeStatuses={ACTIVE_STATUSES}
    badges={
      <>
        <VideoSourceBadge source={record.source_type} />
        <SignalBadge text={signalBadgeText(record.signal, templateLabels)} />
      </>
    }
    titleRight={record.duration_sec > 0 ? <DurationPill seconds={record.duration_sec} /> : undefined}
    footerProps={{ createdAt: record.createdAt, costUsd: record.usage?.cost_usd, showArchive, onArchive }}
  />
)

/** `/engagement` — every engagement report with its status, signal and headline. */
export const EngagementLandingPage = () => {
  const templateLabels = useTemplateLabels()
  return (
    <LandingPageShell<EngagementRecord>
      title="Engagement"
      subtitle="Relate what happens in a video to an engagement curve: peaks, valleys, drivers and recommendations"
      icon={TrendingUp}
      fetchRecords={() => api.engagement.list()}
      archiveRecord={(id) => api.engagement.archive(id)}
      createPath="/engagement/new"
      detailPath="/engagement"
      buttonLabel="New Engagement Analysis"
      gridClassName="grid grid-cols-1 sm:grid-cols-2 gap-4"
      renderCard={(record, onClick, onArchive, showArchive) => (
        <EngagementCard key={record.id} record={record} templateLabels={templateLabels} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
      )}
      emptyTitle="No engagement reports yet"
      emptyDescription="Pick an analysed video and an engagement signal (a built-in template or a BARC file) to see where engagement peaks and dips, and what is on screen when it does."
    />
  )
}
