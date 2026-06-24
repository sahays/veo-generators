import { useEffect, useState, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, ChevronDown, ChevronRight, Download, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { downloadJson } from '@/lib/utils'
import { ModelPill } from '@/components/ModelPill'
import { ServicesUsedPanel } from '@/components/pricing/ServicesUsedPanel'

type Section =
  | 'plan'
  | 'prompt'
  | 'gemini'
  | 'decisions'
  | 'focal-points'
  | 'eval-report'

const CollapsibleCard = ({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: ReactNode
}) => {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-border rounded-xl bg-card overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-5 py-3 text-left hover:bg-muted/30 transition-colors"
      >
        <span className="text-sm font-heading font-bold text-foreground">{title}</span>
        {open ? (
          <ChevronDown size={16} className="text-muted-foreground" />
        ) : (
          <ChevronRight size={16} className="text-muted-foreground" />
        )}
      </button>
      {open && <div className="px-5 pb-5 pt-1 border-t border-border">{children}</div>}
    </div>
  )
}

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
    plan: 'Plan & Quality',
    prompt: 'Gemini Prompt',
    gemini: 'Gemini Scene Analysis',
    decisions: 'Reframe Decisions',
    'focal-points': 'Merged Focal Points',
    'eval-report': 'Quality Report',
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
    const rd = rep.render

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

        {rd && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
              Rendered output ({rd.frames_sampled} frames) <Pill flag={rd.flag} label={rd.flag?.toUpperCase()} />
            </div>
            <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
              <Row flag={flagOf(rd.nonblank_rate, 0.95, 0.8, true)} name="Non-blank frames" value={pct(rd.nonblank_rate)} hint="output isn't black/garbled" />
              <Row flag={flagOf(rd.face_present_rate, 0.7, 0.4, true)} name="Framed face present" value={pct(rd.face_present_rate)} hint="subject landed where predicted" />
              <Row flag={flagOf(rd.position_error_p90, 0.15, 0.3)} name="Position error p90" value={pct(rd.position_error_p90)} hint="output face vs predicted x" />
              {rd.split_panel_fill_rate != null && (
                <Row flag={flagOf(rd.split_panel_fill_rate, 0.8, 0.5, true)} name="Split panels filled" value={pct(rd.split_panel_fill_rate)} hint="both stacked panels show a person" />
              )}
            </div>
          </div>
        )}

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

  const renderPlan = () => {
    const plan = record.segment_plan as Array<any> | undefined
    const summary = record.reframe_summary as any
    const esc = summary?.escalations as
      | { n_points: number; n_clusters: number; n_calls: number; dropped: number }
      | undefined
    return (
      <div className="space-y-4">
        <CollapsibleCard title="Quality">
          {renderEvalReport()}
        </CollapsibleCard>

        <CollapsibleCard title="Plan">
          <div className="space-y-4 text-sm">
            {summary && (
              <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
                <div>{summary.segments} segments &middot; aspect ratios: {JSON.stringify(summary.aspect_ratios)}</div>
                <div>sources: {JSON.stringify(summary.sources)}</div>
                {esc ? (
                  <div className="text-foreground">
                    Gemini decisions: {esc.n_points} point{esc.n_points === 1 ? '' : 's'} &rarr; {esc.n_clusters} cluster{esc.n_clusters === 1 ? '' : 's'} &rarr; {esc.n_calls} call{esc.n_calls === 1 ? '' : 's'}
                    {esc.dropped ? ` · ${esc.dropped} dropped (deterministic fallback)` : ''}
                  </div>
                ) : (
                  <div>Gemini decisions: none needed (all resolved deterministically)</div>
                )}
              </div>
            )}
            {(!plan || plan.length === 0) ? (
              <p className="text-muted-foreground">No plan available for this reframe.</p>
            ) : (
              <div className="space-y-1.5 font-mono text-xs">
                {plan.map((s, i) => {
                  const e = s.escalate
                  const verdict = e?.verdict
                  const ar = s.inner_ar
                  const isLetterbox =
                    Array.isArray(ar) &&
                    !(ar[0] === 9 && ar[1] === 16) &&
                    !(ar[0] === 3 && ar[1] === 4)
                  return (
                    <div key={i} className="space-y-0.5">
                      <div className="flex gap-3">
                        <span className="text-muted-foreground w-24 shrink-0">{fmtT(s.start)}&ndash;{fmtT(s.end)}</span>
                        <span className={`w-12 shrink-0 ${isLetterbox ? 'text-amber-600' : 'text-foreground'}`}>
                          {Array.isArray(ar) ? ar.join(':') : (s.layout === 'split' ? 'split' : '')}
                        </span>
                        <span className="w-20 shrink-0 text-muted-foreground/70">{s.layout}</span>
                        <span className="text-foreground">{(s.trace && s.trace.trigger) || s.reason}</span>
                      </div>
                      {e && (
                        <div className="flex gap-2 pl-24 text-[11px]">
                          <span className="text-amber-600 shrink-0">⚡ Gemini{verdict ? `: ${verdict.action}` : ' (pending)'}</span>
                          <span className="text-muted-foreground/80">{e.question}</span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </CollapsibleCard>
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

      {section === 'plan' ? (
        renderPlan()
      ) : (
        <div className="border border-border rounded-xl p-6 bg-card">
          {section === 'prompt' && renderPrompt()}
          {section === 'gemini' && renderGemini()}
          {section === 'decisions' && renderDecisions()}
          {section === 'focal-points' && renderFocalPoints()}
          {section === 'eval-report' && renderEvalReport()}
        </div>
      )}

      {id && <ServicesUsedPanel feature="reframe" recordId={id} />}
    </div>
  )
}
