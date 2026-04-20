import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'

type Section = 'mediapipe' | 'prompt' | 'gemini' | 'focal-points' | 'chirp'

export const ReframeOutputPage = () => {
  const { id, section } = useParams<{ id: string; section: Section }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api.reframe.get(id)
      .then(setRecord)
      .catch((err: any) => setError(err.message))
      .finally(() => setLoading(false))
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
        <button onClick={() => navigate(`/orientations/${id}`)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={16} /> Back to Reframe
        </button>
        <p className="text-sm text-red-500">{error || 'Record not found'}</p>
      </div>
    )
  }

  const title = record.display_name || record.source_filename || 'Reframe'

  const renderMediapipe = () => {
    const summary = record.track_summary as string | undefined
    if (!summary) {
      return <p className="text-muted-foreground">No MediaPipe track data available. This reframe may have been created before track summaries were stored.</p>
    }
    return (
      <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">{summary}</pre>
    )
  }

  const renderPrompt = () => {
    const fullPrompt = record.prompt_text_used as string | undefined
    if (fullPrompt) {
      return (
        <pre className="text-sm text-foreground whitespace-pre-wrap font-mono leading-relaxed">{fullPrompt}</pre>
      )
    }
    const vars = record.prompt_variables as Record<string, string> | undefined
    if (!vars || Object.keys(vars).length === 0) {
      return <p className="text-muted-foreground">No prompt data available for this reframe.</p>
    }
    const VARIABLE_LABELS: Record<string, string> = {
      content_description: 'Content Type',
      focal_strategy: 'Focal Strategy',
      sampling_instructions: 'Sampling',
      audio_instructions: 'Audio',
      framing_priority: 'Framing',
      extra_rules: 'Rules',
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

  const renderGemini = () => {
    const scenes = record.gemini_scenes as Array<{ start_sec: number; end_sec: number; description: string; active_subject: string; scene_type: string }> | undefined
    if (!scenes || scenes.length === 0) {
      return <p className="text-muted-foreground">No Gemini scene analysis data available for this reframe.</p>
    }
    return (
      <div className="space-y-4 text-sm">
        <p className="text-muted-foreground font-sans">
          {scenes.length} scenes detected
        </p>
        <pre className="text-foreground whitespace-pre-wrap font-mono leading-relaxed text-xs bg-muted/50 rounded-lg p-4 overflow-auto max-h-[70vh]">
          {JSON.stringify(scenes, null, 2)}
        </pre>
      </div>
    )
  }

  const renderFocalPoints = () => {
    const points = record.focal_points as Array<{ time_sec: number; x: number; y: number; confidence?: number; description?: string }> | undefined
    const sceneChanges = record.scene_changes as Array<{ time_sec: number; description?: string }> | undefined
    if (!points || points.length === 0) {
      return <p className="text-muted-foreground">No focal point data available for this reframe.</p>
    }
    const data = {
      focal_points: points,
      scene_changes: sceneChanges || [],
    }
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

  const SECTION_TITLES: Record<string, string> = {
    mediapipe: 'MediaPipe Detection',
    prompt: 'Gemini Prompt',
    gemini: 'Gemini Scene Analysis',
    'focal-points': 'Merged Focal Points',
    // Legacy routes
    chirp: 'Chirp Diarization Output',
  }

  const renderChirp = () => {
    const segments = record.speaker_segments as Array<{ speaker_id: string; start_sec: number; end_sec: number }> | undefined
    if (!segments || segments.length === 0) {
      return <p className="text-muted-foreground">No Chirp diarization data available for this reframe.</p>
    }
    const uniqueSpeakers = [...new Set(segments.map(s => s.speaker_id))].sort()
    const colors = ['text-blue-400', 'text-emerald-400', 'text-amber-400', 'text-rose-400', 'text-purple-400', 'text-cyan-400', 'text-orange-400', 'text-pink-400']
    const colorMap = Object.fromEntries(uniqueSpeakers.map((s, i) => [s, colors[i % colors.length]]))
    const fmtTime = (sec: number) => {
      const m = Math.floor(sec / 60)
      const s = Math.floor(sec % 60)
      return `${m}:${s.toString().padStart(2, '0')}`
    }
    return (
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap gap-3 font-sans">
          <span className="text-muted-foreground">{segments.length} segments</span>
          <span className="text-muted-foreground">&middot;</span>
          <span className="text-muted-foreground">{uniqueSpeakers.length} speakers</span>
        </div>
        <div className="flex flex-wrap gap-2 font-sans">
          {uniqueSpeakers.map(s => (
            <span key={s} className={`text-xs px-2 py-0.5 rounded-full bg-muted ${colorMap[s]}`}>{s}</span>
          ))}
        </div>
        <div className="space-y-0.5 font-mono">
          {segments.map((seg, i) => (
            <div key={i} className="flex gap-4">
              <span className="text-muted-foreground w-28 shrink-0">
                {fmtTime(seg.start_sec)} &ndash; {fmtTime(seg.end_sec)}
              </span>
              <span className={colorMap[seg.speaker_id]}>{seg.speaker_id}</span>
              <span className="text-muted-foreground/50">{(seg.end_sec - seg.start_sec).toFixed(1)}s</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-6 space-y-6">
      <button onClick={() => navigate(`/orientations/${id}`)} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors">
        <ArrowLeft size={16} /> Back to Reframe
      </button>

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-heading font-bold text-foreground">
            {SECTION_TITLES[section || ''] || 'Output'}
          </h1>
          <ModelPill modelName={record?.usage?.model_name} />
        </div>
        <p className="text-sm text-muted-foreground">{title}</p>
      </div>

      <div className="border border-border rounded-xl p-6 bg-card">
        {section === 'mediapipe' && renderMediapipe()}
        {section === 'prompt' && renderPrompt()}
        {section === 'gemini' && renderGemini()}
        {section === 'focal-points' && renderFocalPoints()}
        {section === 'chirp' && renderChirp()}
      </div>

      {id && <ServicesUsedPanel feature="reframe" recordId={id} />}
    </div>
  )
}
