import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Download } from 'lucide-react'
import { Button } from '@/components/Common'
import { downloadJson } from '@/lib/utils'

export interface ReframeSegmentItem {
  start: number
  end: number
  inner_ar?: [number, number] | string
  layout?: string
  reason?: string
  trace?: { trigger?: string }
  escalate?: { verdict?: { action?: string }; question?: string }
}

export interface ReframeSummaryData {
  segments?: number
  aspect_ratios?: Record<string, number>
  sources?: Record<string, number>
  letterbox_16x9_reasons?: Record<string, number>
  speaker_segments?: number
  split_segments?: number
  hysteresis_segments?: number
  escalations?: { n_points: number; n_clusters: number; n_calls: number; dropped: number }
}

export interface ReframeEvalReport {
  overall?: string
  letterbox?: {
    flag?: string
    face_cut_rate?: number | null
    subject_containment?: number | null
    over_letterbox_rate?: number | null
    mean_letterbox_pct?: number | null
  }
  talker?: {
    flag?: string
    av_sync_score?: number | null
    framed_speaker_active_rate?: number | null
    speaker_miss_rate?: number | null
  }
  stability?: {
    flag?: string
    ar_changes_per_min?: number
    crop_jumps_per_min?: number
    center_offset_p50?: number | null
    center_offset_p90?: number | null
  }
  render?: {
    flag?: string
    frames_sampled?: number
    nonblank_rate?: number | null
    face_present_rate?: number | null
    position_error_p90?: number | null
    split_panel_fill_rate?: number | null
  }
  worst?: Array<{ t: number; metric: string; detail: string }>
}

export interface ReframeDetailRecord {
  id: string
  display_name?: string
  source_filename?: string
  status?: string
  prompt_text_used?: string
  prompt_variables?: Record<string, string>
  gemini_scenes?: Array<{
    start_sec: number
    end_sec: number
    description: string
    active_subject: string
    scene_type: string
  }>
  focal_points?: Array<{
    time_sec: number
    x: number
    y: number
    confidence?: number
    description?: string
  }>
  scene_changes?: Array<{ time_sec: number; description?: string }>
  segment_plan?: ReframeSegmentItem[]
  reframe_summary?: ReframeSummaryData
  track_summary?: unknown
  speaker_segments?: unknown
  eval_report?: ReframeEvalReport
  usage?: { model_name?: string; width?: number; height?: number }
}

const FLAG_STYLES: Record<string, string> = {
  ok: 'text-emerald-600 bg-emerald-500/10',
  warn: 'text-amber-600 bg-amber-500/10',
  fail: 'text-red-600 bg-red-500/10',
  na: 'text-muted-foreground bg-muted',
}
const FLAG_ICONS: Record<string, string> = { ok: '✅', warn: '⚠️', fail: '❌', na: '—' }

export function fmtTimeSec(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function flagOf(n: number | null | undefined, warn: number, fail: number, higherBetter = false): string {
  if (n === null || n === undefined) return 'na'
  if (higherBetter) return n <= fail ? 'fail' : n <= warn ? 'warn' : 'ok'
  return n >= fail ? 'fail' : n >= warn ? 'warn' : 'ok'
}

const pct = (n: number | null | undefined) => (n === null || n === undefined ? '—' : `${(n * 100).toFixed(0)}%`)
const num = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toFixed(2))

export const CollapsibleCard = ({
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
      <Button
        variant="unstyled"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 px-5 py-3 text-left hover:bg-muted/30 transition-colors"
      >
        <span className="text-sm font-heading font-bold text-foreground">{title}</span>
        {open ? (
          <ChevronDown size={16} className="text-muted-foreground" />
        ) : (
          <ChevronRight size={16} className="text-muted-foreground" />
        )}
      </Button>
      {open && <div className="px-5 pb-5 pt-1 border-t border-border">{children}</div>}
    </div>
  )
}

const FlagPill = ({ flag = 'na', label }: { flag?: string; label: string }) => (
  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium ${FLAG_STYLES[flag] || FLAG_STYLES.na}`}>
    {FLAG_ICONS[flag] || FLAG_ICONS.na} {label}
  </span>
)

const MetricRow = ({ flag, name, value, hint }: { flag: string; name: string; value: string; hint: string }) => (
  <div className="flex items-center justify-between gap-2">
    <div className="flex items-center gap-2">
      <FlagPill flag={flag} label={value} />
      <span className="text-foreground">{name}</span>
    </div>
    <span className="text-muted-foreground/70 text-xs">{hint}</span>
  </div>
)

const LetterboxAndTalkerEval = ({
  lb,
  tk,
}: {
  lb: NonNullable<ReframeEvalReport['letterbox']>
  tk?: ReframeEvalReport['talker']
}) => (
  <>
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
        Letterboxing &amp; framing <FlagPill flag={lb.flag} label={lb.flag?.toUpperCase() || 'NA'} />
      </div>
      <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
        <MetricRow flag={flagOf(lb.face_cut_rate, 0.05, 0.15)} name="Face cut rate" value={pct(lb.face_cut_rate)} hint="detected faces clipped by the crop" />
        <MetricRow flag={flagOf(lb.subject_containment, 0.9, 0.75, true)} name="Subject containment" value={pct(lb.subject_containment)} hint="framed subject fully in frame" />
        <MetricRow flag={flagOf(lb.over_letterbox_rate, 0.15, 0.35)} name="Over-letterbox rate" value={pct(lb.over_letterbox_rate)} hint="bars a tighter crop didn't need" />
        <MetricRow flag="na" name="Mean letterbox" value={pct(lb.mean_letterbox_pct)} hint="avg blur-bar share of canvas" />
      </div>
    </div>
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
        Showing the talker {tk && <FlagPill flag={tk.flag} label={tk.flag?.toUpperCase() || 'NA'} />}
      </div>
      {tk ? (
        <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
          <MetricRow flag={flagOf(tk.av_sync_score, 0.3, 0.1, true)} name="A/V sync" value={num(tk.av_sync_score)} hint="framed mouth ↔ speech correlation" />
          <MetricRow flag={flagOf(tk.framed_speaker_active_rate, 0.6, 0.4, true)} name="Framed speaker active" value={pct(tk.framed_speaker_active_rate)} hint="framing the one who's talking" />
          <MetricRow flag={flagOf(tk.speaker_miss_rate, 0.1, 0.25)} name="Speaker miss rate" value={pct(tk.speaker_miss_rate)} hint="off-frame face was the talker" />
        </div>
      ) : (
        <p className="text-muted-foreground text-xs bg-muted/50 rounded-lg p-3">
          No dialogue / multi-face audio signal to score (single-subject or no speech).
        </p>
      )}
    </div>
  </>
)

const StabilityAndRenderEval = ({
  st,
  rd,
  worst,
}: {
  st: NonNullable<ReframeEvalReport['stability']>
  rd?: ReframeEvalReport['render']
  worst?: ReframeEvalReport['worst']
}) => (
  <>
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
        Stability {st.flag && <FlagPill flag={st.flag} label={st.flag.toUpperCase()} />}
      </div>
      <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
        <div>aspect-ratio changes: {st.ar_changes_per_min}/min &middot; crop jumps: {st.crop_jumps_per_min}/min</div>
        <div>center offset: p50 {pct(st.center_offset_p50)} &middot; p90 {pct(st.center_offset_p90)}</div>
      </div>
    </div>
    {rd && (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground/70">
          Rendered output ({rd.frames_sampled} frames) <FlagPill flag={rd.flag} label={rd.flag?.toUpperCase() || 'NA'} />
        </div>
        <div className="space-y-1.5 bg-muted/50 rounded-lg p-3">
          <MetricRow flag={flagOf(rd.nonblank_rate, 0.95, 0.8, true)} name="Non-blank frames" value={pct(rd.nonblank_rate)} hint="output isn't black/garbled" />
          <MetricRow flag={flagOf(rd.face_present_rate, 0.7, 0.4, true)} name="Framed face present" value={pct(rd.face_present_rate)} hint="subject landed where predicted" />
          <MetricRow flag={flagOf(rd.position_error_p90, 0.15, 0.3)} name="Position error p90" value={pct(rd.position_error_p90)} hint="output face vs predicted x" />
          {rd.split_panel_fill_rate != null && (
            <MetricRow flag={flagOf(rd.split_panel_fill_rate, 0.8, 0.5, true)} name="Split panels filled" value={pct(rd.split_panel_fill_rate)} hint="both stacked panels show a person" />
          )}
        </div>
      </div>
    )}
    {worst && worst.length > 0 && (
      <div className="space-y-2">
        <div className="text-xs uppercase tracking-wider text-muted-foreground/70">Worst moments</div>
        <div className="space-y-1 font-mono text-xs bg-muted/50 rounded-lg p-3">
          {worst.map((w, i) => (
            <div key={i} className="flex gap-3">
              <span className="text-muted-foreground w-14 shrink-0">{fmtTimeSec(w.t)}</span>
              <span className="w-40 shrink-0 text-amber-600">{w.metric}</span>
              <span className="text-foreground">{w.detail}</span>
            </div>
          ))}
        </div>
      </div>
    )}
  </>
)

export const ReframeEvalReportSection = ({ record }: { record: ReframeDetailRecord }) => {
  const rep = record.eval_report
  if (!rep || !rep.letterbox) {
    return <p className="text-muted-foreground">No quality report available. This reframe may have run before the eval was added, or it is still being analyzed.</p>
  }
  const handleDownload = () => {
    downloadJson(`reframe-eval-${record.id}.json`, {
      id: record.id, display_name: record.display_name, source_filename: record.source_filename, status: record.status,
      src: { width: record.usage?.width, height: record.usage?.height }, eval_report: rep, segment_plan: record.segment_plan,
      reframe_summary: record.reframe_summary, track_summary: record.track_summary, gemini_scenes: record.gemini_scenes, speaker_segments: record.speaker_segments,
    })
  }
  return (
    <div className="space-y-5 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2"><span className="text-muted-foreground text-xs">Overall</span><FlagPill flag={rep.overall} label={rep.overall?.toUpperCase() || 'NA'} /></div>
        <Button variant="outline" size="xs" icon={Download} iconSize={12} onClick={handleDownload}>Download JSON</Button>
      </div>
      <LetterboxAndTalkerEval lb={rep.letterbox} tk={rep.talker} />
      <StabilityAndRenderEval st={rep.stability || {}} rd={rep.render} worst={rep.worst} />
      <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
        Reference-free proxies bounded by detector quality; A/V sync degrades with music or off-screen narration. A tripwire and tuning scoreboard, not a grade.
      </p>
    </div>
  )
}

const PlanSegmentRow = ({ s }: { s: ReframeSegmentItem }) => {
  const e = s.escalate
  const verdict = e?.verdict
  const ar = s.inner_ar
  const isLetterbox = Array.isArray(ar) && !(ar[0] === 9 && ar[1] === 16) && !(ar[0] === 3 && ar[1] === 4)
  return (
    <div className="space-y-0.5">
      <div className="flex gap-3">
        <span className="text-muted-foreground w-24 shrink-0">{fmtTimeSec(s.start)}&ndash;{fmtTimeSec(s.end)}</span>
        <span className={`w-12 shrink-0 ${isLetterbox ? 'text-amber-600' : 'text-foreground'}`}>{Array.isArray(ar) ? ar.join(':') : s.layout === 'split' ? 'split' : ''}</span>
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
}

export const ReframePlanSection = ({ record }: { record: ReframeDetailRecord }) => {
  const plan = record.segment_plan
  const summary = record.reframe_summary
  const esc = summary?.escalations
  return (
    <div className="space-y-4">
      <CollapsibleCard title="Quality"><ReframeEvalReportSection record={record} /></CollapsibleCard>
      <CollapsibleCard title="Plan">
        <div className="space-y-4 text-sm">
          {summary && (
            <div className="font-sans text-xs text-muted-foreground space-y-1 bg-muted/50 rounded-lg p-3">
              <div>{summary.segments} segments &middot; aspect ratios: {JSON.stringify(summary.aspect_ratios)}</div>
              <div>sources: {JSON.stringify(summary.sources)}</div>
              {esc ? (
                <div className="text-foreground">
                  Gemini decisions: {esc.n_points} point{esc.n_points === 1 ? '' : 's'} &rarr; {esc.n_clusters} cluster{esc.n_clusters === 1 ? '' : 's'} &rarr; {esc.n_calls} call{esc.n_calls === 1 ? '' : 's'}{esc.dropped ? ` · ${esc.dropped} dropped (deterministic fallback)` : ''}
                </div>
              ) : (
                <div>Gemini decisions: none needed (all resolved deterministically)</div>
              )}
            </div>
          )}
          {!plan || plan.length === 0 ? (
            <p className="text-muted-foreground">No plan available for this reframe.</p>
          ) : (
            <div className="space-y-1.5 font-mono text-xs">{plan.map((s, i) => <PlanSegmentRow key={i} s={s} />)}</div>
          )}
        </div>
      </CollapsibleCard>
    </div>
  )
}
