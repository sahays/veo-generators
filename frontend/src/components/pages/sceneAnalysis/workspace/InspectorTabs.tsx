import { EntityBrowser, TranscriptPanel } from '@/components/shared/timeline'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { SceneAnalysisRecord } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import { formatSpan } from '@/types/timeline/timeFormat'
import { EventsTab, MomentsTab, ObjectsAdsTab } from './InspectorLists'
import { EmotionChart, ScreenTimeChart } from './OverviewCharts'

const TAB_PANEL_CLASS = 'mt-0 flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden'

function StatTile({ label, value }: { label: string; value: string | number }): JSX.Element {
  return (
    <div className="rounded-md border border-border/70 bg-muted/30 px-2.5 py-1.5">
      <dt className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm font-semibold tabular-nums text-foreground">{value}</dd>
    </div>
  )
}

function OverviewStats({ model, record }: { model: TimelineModel; record: SceneAnalysisRecord }): JSX.Element {
  const doc = model.doc
  return (
    <dl className="grid grid-cols-3 gap-2 sm:grid-cols-6">
      <StatTile label="Length" value={formatSpan(doc.duration_sec)} />
      <StatTile label="Segments" value={doc.segments.length} />
      <StatTile label="Cues" value={doc.cues.length} />
      <StatTile label="Entities" value={doc.entities.length} />
      <StatTile label="Moments" value={doc.key_moments.length} />
      <StatTile label="Windows" value={record.window_count || 1} />
    </dl>
  )
}

/** Summary, counts and the two overview charts. */
function OverviewTab({ model, record }: { model: TimelineModel; record: SceneAnalysisRecord }): JSX.Element {
  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-1">
      {model.doc.content_title && <h3 className="text-sm font-semibold text-foreground">{model.doc.content_title}</h3>}
      <p className="text-xs leading-relaxed text-muted-foreground">{model.doc.summary || 'No summary was produced.'}</p>
      <OverviewStats model={model} record={record} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ScreenTimeChart entities={model.doc.entities} />
        <EmotionChart model={model} />
      </div>
    </div>
  )
}

export interface InspectorTabsProps {
  model: TimelineModel
  record: SceneAnalysisRecord
  className?: string
}

/** Overview | Transcript | Entities | Moments | Events | Objects & Ads. The search box is shared across the tabs. */
export function InspectorTabs({ model, record, className }: InspectorTabsProps): JSX.Element {
  const doc = model.doc
  const objectsAndAdsCount =
    doc.entities.filter((e) => e.kind === 'object').length + (doc.ad_opportunities?.length ?? 0)
  return (
    <Tabs defaultValue="overview" className={className}>
      <TabsList aria-label="Inspector" className="h-auto w-full flex-wrap justify-start">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="transcript">Transcript ({doc.cues.length})</TabsTrigger>
        <TabsTrigger value="entities">Entities ({doc.entities.length})</TabsTrigger>
        <TabsTrigger value="moments">Moments ({doc.key_moments.length})</TabsTrigger>
        <TabsTrigger value="events">Events ({doc.events.length})</TabsTrigger>
        <TabsTrigger value="objects-ads">Objects &amp; Ads ({objectsAndAdsCount})</TabsTrigger>
      </TabsList>
      <TabsContent value="overview" className={TAB_PANEL_CLASS}><OverviewTab model={model} record={record} /></TabsContent>
      <TabsContent value="transcript" className={TAB_PANEL_CLASS}><TranscriptPanel cues={model.cues} className="flex-1" /></TabsContent>
      <TabsContent value="entities" className={TAB_PANEL_CLASS}><EntityBrowser entities={doc.entities} className="flex-1" /></TabsContent>
      <TabsContent value="moments" className={TAB_PANEL_CLASS}><MomentsTab doc={doc} /></TabsContent>
      <TabsContent value="events" className={TAB_PANEL_CLASS}><EventsTab doc={doc} /></TabsContent>
      <TabsContent value="objects-ads" className={TAB_PANEL_CLASS}><ObjectsAdsTab doc={doc} /></TabsContent>
    </Tabs>
  )
}
