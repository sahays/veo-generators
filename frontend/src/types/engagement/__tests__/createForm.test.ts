import { describe, expect, it } from 'vitest'
import type { SignalPreview } from '@/types/insights'
import { engagementCreateSchema } from '@/types/schemas'
import {
  BARC_CHOICE,
  EMPTY_BARC,
  barcFromPreview,
  buildEngagementPayload,
  canStart,
  parseOffset,
  previewIssues,
  type EngagementFormState,
  type VideoChoice,
} from '../createForm'

const ANALYSED: VideoChoice = { kind: 'analysis', analysisId: 'sa-1', name: 'Spot', videoUrl: '/v.mp4' }
const UPLOAD: VideoChoice = { kind: 'source', sourceType: 'upload', sourceId: 'upl-1', name: 'Spot', videoUrl: '/v.mp4' }

const GOOD_PREVIEW: SignalPreview = {
  filename: 'barc.csv',
  row_count: 100,
  columns: ['Date', 'Start Time', 'TVR (%)', 'Reach'],
  time_column: 'Start Time',
  metrics: ['TVR (%)', 'Reach'],
  primary_metric: 'TVR (%)',
  duration_sec: 50,
  interval_sec: 0.5,
  sample_rows: [],
  warnings: [],
}
const UNMAPPED_PREVIEW: SignalPreview = { ...GOOD_PREVIEW, columns: ['Programme', 'Comment'], time_column: null, metrics: [], primary_metric: null, duration_sec: 0, interval_sec: 0 }

function form(overrides: Partial<EngagementFormState>): EngagementFormState {
  return { video: ANALYSED, signalChoice: 'jumpy', barc: EMPTY_BARC, name: '', ...overrides }
}

const firstIssue = (payload: unknown): string | undefined => {
  const parsed = engagementCreateSchema.safeParse(payload)
  return parsed.success ? undefined : parsed.error.issues[0]?.message
}

describe('parseOffset', () => {
  it('reads seconds, treats an empty field as zero and accepts negative and fractional values', () => {
    expect(parseOffset('')).toBe(0)
    expect(parseOffset('  -5 ')).toBe(-5)
    expect(parseOffset('12.5')).toBe(12.5)
  })

  it('rejects text and anything further than a day from zero', () => {
    expect(parseOffset('five')).toBeNull()
    expect(parseOffset('1e9')).toBeNull()
    expect(parseOffset('-86401')).toBeNull()
    expect(parseOffset('86400')).toBe(86400)
  })
})

describe('previewIssues', () => {
  it('is empty for a file whose columns were mapped', () => {
    expect(previewIssues(GOOD_PREVIEW)).toEqual([])
  })

  it('says which kind of column is missing', () => {
    const issues = previewIssues(UNMAPPED_PREVIEW)
    expect(issues).toHaveLength(2)
    expect(issues[0]).toContain('No time column')
    expect(issues[1]).toContain('No numeric metric column')
    expect(previewIssues({ ...GOOD_PREVIEW, metrics: [], primary_metric: null })).toHaveLength(1)
  })
})

describe('canStart', () => {
  it('needs a video and a signal', () => {
    expect(canStart(form({}))).toBe(true)
    expect(canStart(form({ video: null }))).toBe(false)
    expect(canStart(form({ signalChoice: '' }))).toBe(false)
  })

  it('needs an uploaded, mappable file with a valid offset when BARC is chosen', () => {
    const chosen = form({ signalChoice: BARC_CHOICE })
    expect(canStart(chosen)).toBe(false)
    const ready = barcFromPreview('upl-9', GOOD_PREVIEW)
    expect(canStart({ ...chosen, barc: ready })).toBe(true)
    expect(canStart({ ...chosen, barc: { ...ready, offsetText: 'soon' } })).toBe(false)
    expect(canStart({ ...chosen, barc: { ...ready, metric: '' } })).toBe(false)
    expect(canStart({ ...chosen, barc: barcFromPreview('upl-9', UNMAPPED_PREVIEW) })).toBe(false)
  })

  it('ignores a leftover BARC upload once a template is chosen again', () => {
    expect(canStart(form({ signalChoice: 'low', barc: barcFromPreview('upl-9', UNMAPPED_PREVIEW) }))).toBe(true)
  })
})

describe('buildEngagementPayload + engagementCreateSchema', () => {
  it('names an analysed video by its scene analysis and a template by its id', () => {
    const payload = buildEngagementPayload(form({ name: '  Monsoon v2 ' }), { modelId: 'gemini-3.8-flash' })
    expect(payload).toEqual({ scene_analysis_id: 'sa-1', signal: { kind: 'template', template_id: 'jumpy' }, display_name: 'Monsoon v2', model_id: 'gemini-3.8-flash', region: undefined })
    expect(engagementCreateSchema.safeParse(payload).success).toBe(true)
  })

  it('names any other video by its source and carries the BARC mapping and offset', () => {
    const barc = { ...barcFromPreview('upl-9', GOOD_PREVIEW), metric: 'Reach', offsetText: '-5' }
    const payload = buildEngagementPayload(form({ video: UPLOAD, signalChoice: BARC_CHOICE, barc }), {})
    expect(payload.scene_analysis_id).toBeUndefined()
    expect(payload).toMatchObject({ source_type: 'upload', source_id: 'upl-1', signal: { kind: 'barc', upload_id: 'upl-9', time_column: 'Start Time', metric: 'Reach', offset_sec: -5 } })
    expect(engagementCreateSchema.safeParse(payload).success).toBe(true)
  })

  it('rejects a request without a video, or with both ways of naming one', () => {
    expect(firstIssue(buildEngagementPayload(form({ video: null }), {}))).toBe('Please select a video')
    const both = { scene_analysis_id: 'sa-1', source_type: 'upload', source_id: 'upl-1', signal: { kind: 'template', template_id: 'high' } }
    expect(firstIssue(both)).toBe('Please select a video')
    expect(firstIssue({ source_type: 'upload', signal: { kind: 'template', template_id: 'high' } })).toBe('Please select a video')
  })

  it('rejects a missing signal choice, a missing upload and an unusable offset with a plain message', () => {
    expect(firstIssue(buildEngagementPayload(form({ signalChoice: '' }), {}))).toBe('Please choose an engagement signal')
    expect(firstIssue(buildEngagementPayload(form({ signalChoice: BARC_CHOICE }), {}))).toBe('Please upload a BARC file')
    const badOffset = { ...barcFromPreview('upl-9', GOOD_PREVIEW), offsetText: 'soon' }
    expect(firstIssue(buildEngagementPayload(form({ signalChoice: BARC_CHOICE, barc: badOffset }), {}))).toContain('Offset must be a number of seconds')
  })
})
