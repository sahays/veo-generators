import { Captions, FileJson, Table } from 'lucide-react'
import { DownloadMenu, type DownloadGroup } from '@/components/shared/timeline'
import { saveJsonFile, saveTextFile } from '@/hooks/timeline/saveFile'
import type { TimelineDoc } from '@/types/insights'
import {
  TIMELINE_COLLECTION_KEYS,
  TIMELINE_CSV_SPECS,
  cuesToSrt,
  cuesToVtt,
  exportFileStem,
  timelineCollectionCsv,
} from '@/types/timeline/exporters'

export interface ExportMenuProps {
  doc: TimelineDoc
  /** Record name; becomes the stem of the downloaded file names. */
  name: string
}

function csvGroup(doc: TimelineDoc, stem: string): DownloadGroup {
  return {
    label: 'CSV',
    items: TIMELINE_COLLECTION_KEYS.map((key) => ({
      key,
      label: `${TIMELINE_CSV_SPECS[key].label} (${(doc[key] ?? []).length})`,
      icon: Table,
      save: () => saveTextFile(`${stem}-${key}.csv`, timelineCollectionCsv(doc, key), 'text/csv'),
    })),
  }
}

function subtitleGroup(doc: TimelineDoc, stem: string): DownloadGroup {
  return {
    label: 'Subtitles',
    items: [
      { key: 'srt', label: 'SubRip (.srt)', icon: Captions, save: () => saveTextFile(`${stem}.srt`, cuesToSrt(doc.cues), 'application/x-subrip') },
      { key: 'vtt', label: 'WebVTT (.vtt)', icon: Captions, save: () => saveTextFile(`${stem}.vtt`, cuesToVtt(doc.cues), 'text/vtt') },
    ],
  }
}

/** Downloads generated in the browser from the loaded timeline: JSON, one CSV per collection, SRT and VTT. */
export function ExportMenu({ doc, name }: ExportMenuProps): JSX.Element {
  const stem = exportFileStem(name)
  const json: DownloadGroup = {
    items: [{ key: 'json', label: 'Timeline (JSON)', icon: FileJson, save: () => saveJsonFile(`${stem}-timeline.json`, doc) }],
  }
  return <DownloadMenu groups={[json, csvGroup(doc, stem), subtitleGroup(doc, stem)]} />
}
