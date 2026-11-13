import { Clock, FileJson, ScanSearch, Table } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ModelPill } from '@/components/ModelPill'
import { VideoSourceBadge } from '@/components/shared/RecordCard'
import { DownloadMenu, RecordHeader, RecordStatusPill, type DownloadGroup } from '@/components/shared/timeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { saveJsonFile, saveTextFile } from '@/hooks/timeline/saveFile'
import { api } from '@/hooks/useApiClient'
import { getTimeAgo } from '@/lib/utils'
import { curveCsv, driversCsv, extremaCsv } from '@/types/engagement/reportExport'
import { engagementRecordName, reportBadgeText, signalBadgeText } from '@/types/engagement/reportFormat'
import type { EngagementRecord, EngagementReport } from '@/types/insights'
import { exportFileStem } from '@/types/timeline/exporters'
import { formatTimecode } from '@/types/timeline/timeFormat'
import { SignalBadge } from '../SignalBadge'
import { useTemplateLabels } from '../useEngagementTemplates'

/** Link to the scene analysis the report is built on. */
function SceneAnalysisButton({ analysisId }: { analysisId: string }): JSX.Element {
  return (
    <Button asChild variant="outline" size="sm">
      <Link to={`/scene-analysis/${encodeURIComponent(analysisId)}`} data-testid="open-scene-analysis">
        <ScanSearch size={14} aria-hidden /> Scene analysis
      </Link>
    </Button>
  )
}

/** Downloads generated in the browser from the loaded report: the JSON document and three CSVs. */
function ReportExportMenu({ report, name }: { report: EngagementReport; name: string }): JSX.Element {
  const stem = exportFileStem(name)
  const csv = (key: string, label: string, build: (doc: EngagementReport) => string) => ({
    key,
    label,
    icon: Table,
    save: () => saveTextFile(`${stem}-${key}.csv`, build(report), 'text/csv'),
  })
  const groups: DownloadGroup[] = [
    { items: [{ key: 'json', label: 'Report (JSON)', icon: FileJson, save: () => saveJsonFile(`${stem}-engagement-report.json`, report) }] },
    {
      label: 'CSV',
      items: [
        csv('curve', `Curve (${report.signal.point_count} points)`, curveCsv),
        csv('peaks-valleys-drops', `Peaks, valleys and drops (${report.extrema.length})`, extremaCsv),
        csv('drivers', `Drivers (${report.influence.length})`, driversCsv),
      ],
    },
  ]
  return <DownloadMenu groups={groups} />
}

interface HeaderBadgesProps {
  record: EngagementRecord
  report: EngagementReport | null
}

function HeaderBadges({ record, report }: HeaderBadgesProps): JSX.Element {
  const templateLabels = useTemplateLabels()
  const signal = report ? reportBadgeText(report.signal) : signalBadgeText(record.signal, templateLabels)
  return (
    <>
      <RecordStatusPill status={record.status} />
      <VideoSourceBadge source={record.source_type} />
      <SignalBadge text={signal} />
      <ModelPill modelName={record.usage?.model_name || undefined} />
      {record.duration_sec > 0 && (
        <Badge>
          <Clock size={10} aria-hidden /> {formatTimecode(record.duration_sec)}
        </Badge>
      )}
      <span className="text-[11px] text-muted-foreground">{getTimeAgo(record.createdAt)}</span>
    </>
  )
}

export interface EngagementHeaderProps {
  record: EngagementRecord
  /** The loaded report; enables the Export menu. */
  report?: EngagementReport | null
}

/** Back link, editable name, source and signal badges, link to the scene analysis, Export. */
export function EngagementHeader({ record, report = null }: EngagementHeaderProps): JSX.Element {
  const name = engagementRecordName(record)
  const actions = (
    <>
      <SceneAnalysisButton analysisId={record.scene_analysis_id} />
      {report && <ReportExportMenu report={report} name={name} />}
    </>
  )
  return (
    <RecordHeader
      backTo="/engagement"
      backLabel="Back to Engagement"
      name={name}
      onRename={(next) => api.engagement.update(record.id, { display_name: next })}
      badges={<HeaderBadges record={record} report={report} />}
      actions={actions}
    />
  )
}
