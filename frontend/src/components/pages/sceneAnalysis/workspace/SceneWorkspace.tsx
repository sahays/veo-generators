import { useMemo } from 'react'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import { LoadFailure, LoadingNotice, NowStrip, SyncedVideoPlayer, TimelineWorkspace } from '@/components/shared/timeline'
import type { SceneAnalysisRecord, TimelineResponse } from '@/types/insights'
import { buildTimelineModel, defaultPinnedEntityIds } from '@/types/timeline/model'
import { ExportMenu } from './ExportMenu'
import { InspectorTabs } from './InspectorTabs'
import { SceneTimeline } from './SceneTimeline'
import { useSceneTimeline } from './useSceneAnalysis'
import { RunEngagementButton, WorkspaceHeader, recordName } from './WorkspaceHeader'

interface LoadedWorkspaceProps {
  record: SceneAnalysisRecord
  data: TimelineResponse
}

/** Layout of a completed analysis: player and inspector side by side, timeline below. */
function LoadedWorkspace({ record, data }: LoadedWorkspaceProps): JSX.Element {
  const model = useMemo(() => buildTimelineModel(data.timeline), [data.timeline])
  const initial = useMemo(() => ({ pinnedEntityIds: defaultPinnedEntityIds(data.timeline.entities) }), [data.timeline])
  return (
    <TimelineWorkspace duration={model.duration} items={model.itemsById} initial={initial}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <SyncedVideoPlayer src={record.video_signed_url} segments={model.segments} title={recordName(record)}>
          <NowStrip model={model} />
        </SyncedVideoPlayer>
        <InspectorTabs model={model} record={record} className="flex h-[30rem] min-h-0 flex-col gap-3 rounded-xl border border-border bg-card p-3 xl:h-auto xl:max-h-[38rem]" />
      </div>
      <SceneTimeline model={model} filmstrip={data.filmstrip} />
      <ServicesUsedPanel feature="scene_analysis" recordId={record.id} />
    </TimelineWorkspace>
  )
}

/** A completed analysis: loads the timeline document, then shows the workspace. */
export function SceneWorkspace({ record }: { record: SceneAnalysisRecord }): JSX.Element {
  const { data, error, reload } = useSceneTimeline(record.id)
  const actions = (
    <>
      <RunEngagementButton analysisId={record.id} />
      {data && <ExportMenu doc={data.timeline} name={recordName(record)} />}
    </>
  )
  return (
    <>
      <WorkspaceHeader record={record} actions={actions} />
      {data && <LoadedWorkspace record={record} data={data} />}
      {!data && (error ? <LoadFailure error={error} onRetry={reload} /> : <LoadingNotice label="Loading timeline…" />)}
    </>
  )
}
