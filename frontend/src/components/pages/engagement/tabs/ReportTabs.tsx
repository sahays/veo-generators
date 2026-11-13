import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { ReportModel } from '@/types/engagement/reportModel'
import type { EngagementRecord } from '@/types/insights'
import type { TimelineModel } from '@/types/timeline/model'
import { SimulatedNote } from '../ReportBits'
import { DataTab } from './DataTab'
import { DriversTab } from './DriversTab'
import { ExtremaTab } from './ExtremaTab'
import { OverviewTab } from './OverviewTab'
import { RecommendationsTab } from './RecommendationsTab'

export interface ReportTabsProps {
  report: ReportModel
  timeline: TimelineModel
  record: EngagementRecord
}

interface PanelProps {
  value: string
  /** Template curves are illustrative: every tab with numbers derived from one says so. */
  simulated: boolean
  children: React.ReactNode
}

function Panel({ value, simulated, children }: PanelProps): JSX.Element {
  return (
    <TabsContent value={value} className="mt-0 space-y-3">
      {simulated && <SimulatedNote />}
      {children}
    </TabsContent>
  )
}

/** Overview | Peaks & Valleys | Drivers | Recommendations | Data. */
export function ReportTabs({ report, timeline, record }: ReportTabsProps): JSX.Element {
  const simulated = report.report.signal.simulated
  const { extrema, influence } = report.report
  return (
    <Tabs defaultValue="overview" data-testid="report-tabs" className="space-y-3 rounded-xl border border-border bg-card p-3">
      <TabsList aria-label="Report" className="h-auto w-full flex-wrap justify-start">
        <TabsTrigger value="overview">Overview</TabsTrigger>
        <TabsTrigger value="extrema">Peaks &amp; Valleys ({extrema.length})</TabsTrigger>
        <TabsTrigger value="drivers">Drivers ({influence.length})</TabsTrigger>
        <TabsTrigger value="recommendations">Recommendations</TabsTrigger>
        <TabsTrigger value="data">Data</TabsTrigger>
      </TabsList>
      <Panel value="overview" simulated={simulated}><OverviewTab report={report} timeline={timeline} /></Panel>
      <Panel value="extrema" simulated={simulated}><ExtremaTab report={report} timeline={timeline} /></Panel>
      <Panel value="drivers" simulated={simulated}><DriversTab report={report} /></Panel>
      <Panel value="recommendations" simulated={simulated}><RecommendationsTab report={report} timeline={timeline} jobNote={record.stage_detail} /></Panel>
      <Panel value="data" simulated={false}><DataTab report={report} record={record} /></Panel>
    </Tabs>
  )
}
