import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Download, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { downloadJson } from '@/lib/utils'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'

type Section =
  | 'mediapipe'
  | 'prompt'
  | 'gemini'
  | 'decisions'
  | 'focal-points'
  | 'chirp'
  | 'eval-report'

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
    decisions: 'Reframe Decisions',
    'focal-points': 'Merged Focal Points',
    'eval-report': 'Quality Report',
    // Legacy routes
    chirp: 'Chirp Diarization Output',
  }

  const fmtT = (sec: number) => {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const renderDecisions = () => {
    const plan = record.segment_plan as Array<any> | undefined
    const summary = record.reframe_summary as any
    if (!plan || plan.length === 0) {
      return <p className="text-muted-foreground">No decision plan available for this reframe.</p>
    }
    return (
      <div className="space-y-4 text-sm">
        {summary && (
          <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
            <div>{summary.segments} segments &middot; aspect ratios: {JSON.stringify(summary.aspect_ratios)}</div>
            <div>sources: {JSON.stringify(summary.sources)}</div>
            {summary.letterbox_16x9_reasons && Object.keys(summary.letterbox_16x9_reasons).length > 0 && (
              <div>16:9 letterbox because: {JSON.stringify(summary.letterbox_16x9_reasons)}</div>
            )}
            <div>active-speaker segments: {summary.speaker_segments ?? 0} &middot; split: {summary.split_segments ?? 0} &middot; hysteresis: {summary.hysteresis_segments ?? 0}</div>
          </div>
        )}
        <div className="space-y-1 font-mono text-xs">
          {plan.map((s, i) => (
            <div key={i} className="flex gap-3">
              <span className="text-muted-foreground w-24 shrink-0">{fmtT(s.start)}&ndash;{fmtT(s.end)}</span>
              <span className="w-12 shrink-0 text-foreground">{Array.isArray(s.inner_ar) ? s.inner_ar.join(':') : (s.layout === 'split' ? 'split' : '')}</span>
              <span className="w-20 shrink-0 text-muted-foreground/70">{s.layout}</span>
              <span className="text-foreground">{(s.trace && s.trace.trigger) || s.reason}</span>
            </div>
          ))}
        </div>
      </div>
    )
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

  const renderEvalReport = () => {
    const rep = record.eval_report as any
    if (!rep || !rep.letterbox) {
      return <p className="text-muted-foreground">No quality report available. This reframe may have run before the eval was added, or it is still being analyzed.</p>
    }

    const FLAG: Record<string, string> = {
      ok: 'text-emerald-600 bg-emerald-500/10',
      warn: 'text-amber-600 bg-amber-500/10',
      fail: 'text-red-600 bg-red-500/10',
      na: 'text-muted-foreground bg-muted',
    }
    const ICON: Record<string, string> = { ok: '✅', warn: '⚠️', fail: '❌', na: '—' }
    const flagOf = (n: number | null | undefined, warn: number, fail: number, higherBetter = false): string => {
      if (n === null || n === undefined) return 'na'
      if (higherBetter) return n <= fail ? 'fail' : n <= warn ? 'warn' : 'ok'
      return n >= fail ? 'fail' : n >= warn ? 'warn' : 'ok'
    }
    const pct = (n: number | null | undefined) => (n === null || n === undefined ? '—' : `${(n * 100).toFixed(0)}%`)
    const num = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toFixed(2))

    const Pill = ({ flag, label }: { flag: string; label: string }) => (
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${FLAG[flag] || FLAG.na}`}>
        {ICON[flag] || ICON.na} {label}
      </span>
    )
    const Row = ({ flag, name, value, hint }: { flag: string; name: string; value: string; hint: string }) => (
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Pill flag={flag} label={value} />
          <span className="text-foreground">{name}</span>
        </div>
        <span className="text-muted-foreground/70 text-xs">{hint}</span>
      </div>
    )

    const lb = rep.letterbox
    const tk = rep.talker
    const st = rep.stability || {}

    const handleDownload = () => {
      downloadJson(`reframe-eval-${record.id}.json`, {
        id: record.id,
        display_name: record.display_name,
        source_filename: record.source_filename,
        status: record.status,
        src: { width: record.usage?.width, height: record.usage?.height },
        eval_report: rep,
        segment_plan: record.segment_plan,
        reframe_summary: record.reframe_summary,
        track_summary: record.track_summary,
        gemini_scenes: record.gemini_scenes,
        speaker_segments: record.speaker_segments,
      })
    }

    return (
      <div className="space-y-5 text-sm">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground text-xs">Overall</span>
            <Pill flag={rep.overall} label={rep.overall?.toUpperCase() || 'NA'} />
          </div>
          <button
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
          >
            <Download size={12} /> Download JSON
          </button>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
            Letterboxing &amp; framing <Pill flag={lb.flag} label={lb.flag?.toUpperCase()} />
          </div>
          <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
            <Row flag={flagOf(lb.face_cut_rate, 0.05, 0.15)} name="Face cut rate" value={pct(lb.face_cut_rate)} hint="detected faces clipped by the crop" />
            <Row flag={flagOf(lb.subject_containment, 0.9, 0.75, true)} name="Subject containment" value={pct(lb.subject_containment)} hint="framed subject fully in frame" />
            <Row flag={flagOf(lb.over_letterbox_rate, 0.15, 0.35)} name="Over-letterbox rate" value={pct(lb.over_letterbox_rate)} hint="bars a tighter crop didn't need" />
            <Row flag="na" name="Mean letterbox" value={pct(lb.mean_letterbox_pct)} hint="avg blur-bar share of canvas" />
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
            Showing the talker {tk && <Pill flag={tk.flag} label={tk.flag?.toUpperCase()} />}
          </div>
          {tk ? (
            <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
              <Row flag={flagOf(tk.av_sync_score, 0.3, 0.1, true)} name="A/V sync" value={num(tk.av_sync_score)} hint="framed mouth ↔ speech correlation" />
              <Row flag={flagOf(tk.framed_speaker_active_rate, 0.6, 0.4, true)} name="Framed speaker active" value={pct(tk.framed_speaker_active_rate)} hint="framing the one who's talking" />
              <Row flag={flagOf(tk.speaker_miss_rate, 0.1, 0.25)} name="Speaker miss rate" value={pct(tk.speaker_miss_rate)} hint="off-frame face was the talker" />
            </div>
          ) : (
            <p className="text-muted-foreground text-xs bg-muted/50 rounded-lg p-3">No dialogue / multi-face audio signal to score (single-subject or no speech).</p>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
            Stability {st.flag && <Pill flag={st.flag} label={st.flag?.toUpperCase()} />}
          </div>
          <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
            <div>aspect-ratio changes: {st.ar_changes_per_min}/min &middot; crop jumps: {st.crop_jumps_per_min}/min</div>
            <div>center offset: p50 {pct(st.center_offset_p50)} &middot; p90 {pct(st.center_offset_p90)}</div>
          </div>
        </div>

        {rep.worst && rep.worst.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs uppercase tracking-wider text-muted-foreground/70">Worst moments</div>
            <div className="space-y-1 font-mono text-xs bg-muted/50 rounded-lg p-3">
              {rep.worst.map((w: any, i: number) => (
                <div key={i} className="flex gap-3">
                  <span className="text-muted-foreground w-14 shrink-0">{fmtT(w.t)}</span>
                  <span className="w-40 shrink-0 text-amber-600">{w.metric}</span>
                  <span className="text-foreground">{w.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
          Reference-free proxies bounded by detector quality; A/V sync degrades with music or
          off-screen narration. A tripwire and tuning scoreboard, not a grade.
        </p>
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
        {section === 'decisions' && renderDecisions()}
        {section === 'focal-points' && renderFocalPoints()}
        {section === 'eval-report' && renderEvalReport()}
        {section === 'chirp' && renderChirp()}
      </div>

      {id && <ServicesUsedPanel feature="reframe" recordId={id} />}
    </div>
  )
}
