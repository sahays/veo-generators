import type { EngagementCreate, EngagementSignalSpec, InsightSourceType, SignalPreview } from '@/types/insights'

/** Radio value of the "Upload a BARC file" option; every other value is a template id. */
export const BARC_CHOICE = 'barc'
/** The server accepts offsets within a day of zero. */
export const MAX_OFFSET_SEC = 86400

/** The video an engagement job runs on: an existing scene analysis, or a video that is analysed first. */
export type VideoChoice =
  | { kind: 'analysis'; analysisId: string; name: string; videoUrl: string }
  | { kind: 'source'; sourceType: InsightSourceType; sourceId: string; name: string; videoUrl: string }

/** An uploaded BARC file and how its columns map onto the signal. */
export interface BarcSelection {
  uploadId: string | null
  preview: SignalPreview | null
  timeColumn: string
  metric: string
  /** Raw text of the offset field, in seconds. */
  offsetText: string
}

export interface EngagementFormState {
  video: VideoChoice | null
  /** A template id, `BARC_CHOICE`, or '' while nothing is chosen. */
  signalChoice: string
  barc: BarcSelection
  name: string
}

export const EMPTY_BARC: BarcSelection = { uploadId: null, preview: null, timeColumn: '', metric: '', offsetText: '0' }

/** Offset in seconds from the field's text ('' means 0), or null when it is not a usable number. */
export function parseOffset(text: string): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return 0
  const value = Number(trimmed)
  return Number.isFinite(value) && Math.abs(value) <= MAX_OFFSET_SEC ? value : null
}

/**
 * Why a previewed CSV cannot be used as a signal, in plain words; empty when
 * its columns could be mapped. The server's own notes are in `preview.warnings`.
 */
export function previewIssues(preview: SignalPreview): string[] {
  const issues: string[] = []
  if (!preview.time_column) {
    issues.push('No time column was found. The file needs a column such as "Start Time", "Time" or seconds from the start of the video.')
  }
  if (preview.metrics.length === 0 || !preview.primary_metric) {
    issues.push('No numeric metric column was found. The file needs at least one column of numbers such as TVR, Impressions or Reach.')
  }
  return issues
}

/** The BARC selection with the mapping the preview detected. */
export function barcFromPreview(uploadId: string, preview: SignalPreview): BarcSelection {
  return { uploadId, preview, timeColumn: preview.time_column ?? '', metric: preview.primary_metric ?? '', offsetText: '0' }
}

function barcReady(barc: BarcSelection): boolean {
  if (!barc.uploadId || !barc.preview || previewIssues(barc.preview).length > 0) return false
  return Boolean(barc.timeColumn && barc.metric) && parseOffset(barc.offsetText) !== null
}

/** True when the form has everything a create request needs. */
export function canStart(form: EngagementFormState): boolean {
  if (!form.video || !form.signalChoice) return false
  return form.signalChoice === BARC_CHOICE ? barcReady(form.barc) : true
}

function signalFields(form: EngagementFormState): EngagementSignalSpec {
  if (form.signalChoice !== BARC_CHOICE) return { kind: 'template', template_id: form.signalChoice }
  const { uploadId, timeColumn, metric, offsetText } = form.barc
  return { kind: 'barc', upload_id: uploadId ?? '', time_column: timeColumn, metric, offset_sec: parseOffset(offsetText) ?? Number.NaN }
}

function videoFields(video: VideoChoice | null): Pick<EngagementCreate, 'scene_analysis_id' | 'source_type' | 'source_id'> {
  if (!video) return {}
  if (video.kind === 'analysis') return { scene_analysis_id: video.analysisId }
  return { source_type: video.sourceType, source_id: video.sourceId }
}

/** The create request for the form as it stands. Validate it with `engagementCreateSchema` before sending. */
export function buildEngagementPayload(form: EngagementFormState, model: { modelId?: string; region?: string }): EngagementCreate {
  return {
    ...videoFields(form.video),
    signal: signalFields(form),
    display_name: form.name.trim() || undefined,
    model_id: model.modelId,
    region: model.region,
  }
}
