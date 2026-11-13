import { ScanSearch } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard, VideoSourceBadge } from '@/components/shared/RecordCard'
import { DurationPill } from '@/components/shared/timeline'
import type { SceneAnalysisRecord } from '@/types/insights'

const ACTIVE_STATUSES = ['pending', 'analyzing', 'processing']

// Keys of `record.counts` as written by the worker, in display order.
const COUNT_CHIPS: { key: string; one: string; many: string }[] = [
  { key: 'segments', one: 'segment', many: 'segments' },
  { key: 'cues', one: 'cue', many: 'cues' },
  { key: 'entities', one: 'entity', many: 'entities' },
  { key: 'events', one: 'event', many: 'events' },
  { key: 'emotions', one: 'emotion', many: 'emotions' },
  { key: 'key_moments', one: 'moment', many: 'moments' },
  { key: 'narrative_beats', one: 'beat', many: 'beats' },
]

interface SceneAnalysisCardProps {
  record: SceneAnalysisRecord
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}

const CountChips = ({ counts }: { counts: Record<string, number> }) => {
  const chips = COUNT_CHIPS.filter(({ key }) => (counts[key] ?? 0) > 0)
  if (chips.length === 0) return null
  return (
    <div className="flex items-center gap-1 mb-3 flex-wrap">
      {chips.map(({ key, one, many }) => (
        <span key={key} className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
          {counts[key]} {counts[key] === 1 ? one : many}
        </span>
      ))}
    </div>
  )
}

const SceneAnalysisCard = ({ record, onClick, onArchive, showArchive }: SceneAnalysisCardProps) => (
  <RecordCard
    onClick={onClick}
    title={record.display_name || record.content_title || record.video_filename || 'Untitled video'}
    description={record.summary || undefined}
    status={record.status}
    statusIcon={ScanSearch}
    progressPct={record.progress_pct}
    activeStatuses={ACTIVE_STATUSES}
    badges={<VideoSourceBadge source={record.source_type} />}
    titleRight={record.duration_sec > 0 ? <DurationPill seconds={record.duration_sec} /> : undefined}
    footerProps={{
      createdAt: record.createdAt,
      costUsd: record.usage?.cost_usd,
      showArchive,
      onArchive,
    }}
  >
    <CountChips counts={record.counts ?? {}} />
  </RecordCard>
)

export const SceneAnalysisLandingPage = () => (
  <LandingPageShell<SceneAnalysisRecord>
    title="Scene Analysis"
    subtitle="Timestamped breakdowns of scenes, dialogue, entities, emotions and key moments"
    icon={ScanSearch}
    fetchRecords={() => api.sceneAnalysis.list()}
    archiveRecord={(id) => api.sceneAnalysis.archive(id)}
    createPath="/scene-analysis/new"
    detailPath="/scene-analysis"
    buttonLabel="New Analysis"
    gridClassName="grid grid-cols-1 sm:grid-cols-2 gap-4"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <SceneAnalysisCard key={record.id} record={record} onClick={onClick} onArchive={onArchive} showArchive={showArchive} />
    )}
    emptyTitle="No scene analyses yet"
    emptyDescription="Pick an uploaded video or a completed production to get a timestamped breakdown of its scenes, dialogue, entities and emotions."
  />
)
