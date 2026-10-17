import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/hooks/useApiClient'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'
import {
  fmtTimeSec,
  ReframeEvalReportSection,
  ReframePlanSection,
  type ReframeDetailRecord,
} from '@/components/pages/reframe/components/ReframeOutputSections'

type Section =
  | 'plan'
  | 'prompt'
  | 'gemini'
  | 'decisions'
  | 'focal-points'
  | 'eval-report'

const SECTION_TITLES: Record<string, string> = {
  plan: 'Plan & Quality',
  prompt: 'Gemini Prompt',
  gemini: 'Gemini Scene Analysis',
  decisions: 'Reframe Decisions',
  'focal-points': 'Merged Focal Points',
  'eval-report': 'Quality Report',
}

const VARIABLE_LABELS: Record<string, string> = {
  content_description: 'Content Type',
  focal_strategy: 'Focal Strategy',
  sampling_instructions: 'Sampling',
  audio_instructions: 'Audio',
  framing_priority: 'Framing',
  extra_rules: 'Rules',
}

const ReframePromptSection = ({ record }: { record: ReframeDetailRecord }) => {
  if (record.prompt_text_used) {
    return (
      <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">
        {record.prompt_text_used}
      </pre>
    )
  }
  const vars = record.prompt_variables
  if (!vars || Object.keys(vars).length === 0) {
    return <p className="text-muted-foreground">No prompt data available for this reframe.</p>
  }
  return (
    <div className="space-y-6">
      {Object.entries(vars).map(([key, value]) => (
        <div key={key}>
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1">
            {VARIABLE_LABELS[key] || key}
          </h3>
          <p className="text-sm text-foreground whitespace-pre-line">{value}</p>
        </div>
      ))}
    </div>
  )
}

const ReframeGeminiSection = ({ record }: { record: ReframeDetailRecord }) => {
  const scenes = record.gemini_scenes
  if (!scenes || scenes.length === 0) {
    return <p className="text-muted-foreground">No Gemini scene analysis data available for this reframe.</p>
  }
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground font-sans">{scenes.length} scenes detected</p>
      <pre className="text-foreground whitespace-pre-wrap font-mono leading-relaxed text-xs bg-muted/50 rounded-lg p-4 overflow-auto max-h-[70vh]">
        {JSON.stringify(scenes, null, 2)}
      </pre>
    </div>
  )
}

const ReframeFocalPointsSection = ({ record }: { record: ReframeDetailRecord }) => {
  const points = record.focal_points
  const sceneChanges = record.scene_changes
  if (!points || points.length === 0) {
    return <p className="text-muted-foreground">No focal point data available for this reframe.</p>
  }
  const data = { focal_points: points, scene_changes: sceneChanges || [] }
  return (
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground font-sans">
        {points.length} focal points, {sceneChanges?.length || 0} scene changes
      </p>
      <pre className="text-foreground whitespace-pre-wrap font-mono leading-relaxed text-xs bg-muted/50 rounded-lg p-4 overflow-auto max-h-[70vh]">
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  )
}

const ReframeDecisionsSection = ({ record }: { record: ReframeDetailRecord }) => {
  const plan = record.segment_plan
  const summary = record.reframe_summary
  if (!plan || plan.length === 0) return <p className="text-muted-foreground">No decision plan available for this reframe.</p>
  return (
    <div className="space-y-4 text-sm">
      {summary && (
        <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
          <div>{summary.segments} segments &middot; aspect ratios: {JSON.stringify(summary.aspect_ratios)}</div>
          <div>sources: {JSON.stringify(summary.sources)}</div>
          {summary.letterbox_16x9_reasons && Object.keys(summary.letterbox_16x9_reasons).length > 0 && <div>16:9 letterbox because: {JSON.stringify(summary.letterbox_16x9_reasons)}</div>}
          <div>active-speaker segments: {summary.speaker_segments ?? 0} &middot; split: {summary.split_segments ?? 0} &middot; hysteresis: {summary.hysteresis_segments ?? 0}</div>
        </div>
      )}
      <div className="space-y-1 font-mono text-xs">
        {plan.map((s, i) => (
          <div key={i} className="flex gap-3">
            <span className="text-muted-foreground w-24 shrink-0">{fmtTimeSec(s.start)}&ndash;{fmtTimeSec(s.end)}</span>
            <span className="w-12 shrink-0 text-foreground">{Array.isArray(s.inner_ar) ? s.inner_ar.join(':') : s.layout === 'split' ? 'split' : ''}</span>
            <span className="w-20 shrink-0 text-muted-foreground/70">{s.layout}</span>
            <span className="text-foreground">{(s.trace && s.trace.trigger) || s.reason}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const ReframeOutputBody = ({ id, section, record, onBack }: { id?: string; section?: Section; record: ReframeDetailRecord; onBack: () => void }) => (
  <div className="max-w-3xl mx-auto py-8 px-6 space-y-6">
    <Button variant="link" icon={ArrowLeft} onClick={onBack} className="text-sm">Back to Reframe</Button>
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-heading font-bold text-foreground">{SECTION_TITLES[section || ''] || 'Output'}</h1>
        <ModelPill modelName={record.usage?.model_name} />
      </div>
      <p className="text-sm text-muted-foreground">{record.display_name || record.source_filename || 'Reframe'}</p>
    </div>
    {section === 'plan' ? (
      <ReframePlanSection record={record} />
    ) : (
      <div className="border border-border rounded-xl p-6 bg-card">
        {section === 'prompt' && <ReframePromptSection record={record} />}
        {section === 'gemini' && <ReframeGeminiSection record={record} />}
        {section === 'decisions' && <ReframeDecisionsSection record={record} />}
        {section === 'focal-points' && <ReframeFocalPointsSection record={record} />}
        {section === 'eval-report' && <ReframeEvalReportSection record={record} />}
      </div>
    )}
    {id && <ServicesUsedPanel feature="reframe" recordId={id} />}
  </div>
)

export const ReframeOutputPage = () => {
  const { id, section } = useParams<{ id: string; section: Section }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<ReframeDetailRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api.reframe.get(id).then((res) => setRecord(res as unknown as ReframeDetailRecord)).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load reframe')).finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    )
  }
  if (error || !record) {
    return (
      <div className="space-y-4 max-w-3xl mx-auto py-12 px-6">
        <Button variant="link" icon={ArrowLeft} onClick={() => navigate(`/orientations/${id}`)} className="text-sm">Back to Reframe</Button>
        <p className="text-sm text-red-500">{error || 'Record not found'}</p>
      </div>
    )
  }
  return <ReframeOutputBody id={id} section={section} record={record} onBack={() => navigate(`/orientations/${id}`)} />
}
