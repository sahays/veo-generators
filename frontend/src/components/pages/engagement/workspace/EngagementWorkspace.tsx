import { useMemo } from 'react'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { LoadFailure, LoadingNotice, SyncedVideoPlayer, TimelineWorkspace } from '@/components/shared/timeline'
import { engagementRecordName } from '@/types/engagement/reportFormat'
import { buildReportModel } from '@/types/engagement/reportModel'
import type { EngagementRecord } from '@/types/insights'
import { buildTimelineModel, defaultPinnedEntityIds } from '@/types/timeline/model'
import { ReportTabs } from '../tabs/ReportTabs'
import { EngagementHeader } from './EngagementHeader'
import { EngagementTimeline } from './EngagementTimeline'
import { EngagementUiProvider } from './engagementUi'
import { MomentPanel } from './MomentPanel'
import { RangeInspector } from './RangeInspector'
import { useEngagementDocs, type EngagementDocs } from './useEngagement'

interface LoadedWorkspaceProps {
  record: EngagementRecord
  docs: EngagementDocs
}

/** Layout of a completed report: player, "At this moment" and the range inspector side by side, the timeline, then the report tabs. */
function LoadedWorkspace({ record, docs }: LoadedWorkspaceProps): JSX.Element {
  const timeline = useMemo(() => buildTimelineModel(docs.scene.timeline), [docs.scene.timeline])
  const report = useMemo(() => buildReportModel(docs.report), [docs.report])
  // Scene items and extrema are both addressable, so `?sel=seg-2` and `?sel=peak-1` can be restored from a link.
  const items = useMemo(() => new Map([...timeline.itemsById, ...report.itemRefs]), [timeline, report])
  const initial = useMemo(() => ({ pinnedEntityIds: defaultPinnedEntityIds(docs.scene.timeline.entities) }), [docs.scene.timeline])
  return (
    <TimelineWorkspace duration={timeline.duration} items={items} initial={initial}>
      <EngagementUiProvider report={report}>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,3.5fr)_minmax(0,3.5fr)]">
          <SyncedVideoPlayer src={record.video_signed_url} segments={timeline.segments} title={engagementRecordName(record)} />
          <MomentPanel report={report} timeline={timeline} />
          <RangeInspector report={report} timeline={timeline} />
        </div>
        <EngagementTimeline report={report} timeline={timeline} />
        <ReportTabs report={report} timeline={timeline} record={record} />
        <ServicesUsedPanel feature="engagement" recordId={record.id} />
      </EngagementUiProvider>
    </TimelineWorkspace>
  )
}

/** A completed report: loads `report.json` and the scene timeline, then shows the workspace. */
export function EngagementWorkspace({ record }: { record: EngagementRecord }): JSX.Element {
  const { data, error, reload } = useEngagementDocs(record)
  return (
    <>
      <EngagementHeader record={record} report={data?.report} />
      {data && <LoadedWorkspace record={record} docs={data} />}
      {!data && (error ? <LoadFailure error={error} onRetry={reload} /> : <LoadingNotice label="Loading report…" />)}
    </>
  )
}
