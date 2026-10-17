import { useState, useMemo } from 'react'
import {
  CheckCircle2,
  XCircle,
  Sparkles,
  User,
  MapPin,
  Box,
  Film,
  Music,
  ShieldCheck,
  Terminal,
  RefreshCw,
  Loader2,
  Play,
  AlertTriangle,
  GitBranch,
  History,
  Eye,
  Orbit,
  FileText,
  Layers,
  ChevronRight,
  ChevronDown,
  Sliders,
  Clock,
  Cpu,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { StoryGraphVisualizer3D } from '@/components/ads/StoryGraphVisualizer3D'
import type { StoryGraphData } from '@/types/project'

type ActiveStepId =
  | 's1_world'
  | 's2_scripts'
  | 's3_images'
  | 's4_s5_shots'
  | 's6_s7_compile'
  | 's8_s10_videos'

interface SelectedInspectorItem {
  kind: 'stage' | 'entity' | 'scene' | 'appearance' | 'shot' | 'video_run'
  id: string
  data: any
}

const PIPELINE_SUB_STAGES: Array<{
  id: string
  short: string
  label: string
  role: string
  stepGroup: ActiveStepId
  gate?: 'G1' | 'G2' | 'G3'
}> = [
  {
    id: 'S1_EXTRACT',
    short: 'S1',
    label: 'World & Entities',
    role: 'STORY_ARCHITECT + SUPERVISOR',
    stepGroup: 's1_world',
    gate: 'G1',
  },
  {
    id: 'S2_SCREENPLAY',
    short: 'S2',
    label: 'Scene Scripts',
    role: 'SCREENWRITER',
    stepGroup: 's2_scripts',
  },
  {
    id: 'S3_DESIGN',
    short: 'S3',
    label: 'Reference Images',
    role: 'CHAR / LOC / OBJ DESIGNERS',
    stepGroup: 's3_images',
    gate: 'G2',
  },
  {
    id: 'S4_SHOTS',
    short: 'S4',
    label: 'Shot Breakdown',
    role: 'DIRECTOR',
    stepGroup: 's4_s5_shots',
  },
  {
    id: 'S5_MUSIC',
    short: 'S5',
    label: 'Music & SFX',
    role: 'MUSIC_DIRECTOR',
    stepGroup: 's4_s5_shots',
    gate: 'G3',
  },
  {
    id: 'S6_VALIDATE',
    short: 'S6',
    label: 'Validator V1–V13',
    role: 'DETERMINISTIC',
    stepGroup: 's6_s7_compile',
  },
  {
    id: 'S7_COMPILE',
    short: 'S7',
    label: 'Prompt Compiler',
    role: 'BUDGETER + JINJA2',
    stepGroup: 's6_s7_compile',
  },
  {
    id: 'S8_RENDER',
    short: 'S8',
    label: 'Video Render',
    role: 'GEMINI OMNI / VEO',
    stepGroup: 's8_s10_videos',
  },
  {
    id: 'S9_QA',
    short: 'S9',
    label: 'Clip VLM QA',
    role: 'CRITIC VLM',
    stepGroup: 's8_s10_videos',
  },
  {
    id: 'S10_ASSEMBLE',
    short: 'S10',
    label: 'Final Cut',
    role: 'FFMPEG ASSEMBLER',
    stepGroup: 's8_s10_videos',
  },
]

interface StoryGraphStudioPanelProps {
  productionId: string
  storyGraph?: StoryGraphData
  currentStage?: string
  pipelineStatus?: string
  pipelineError?: string | null
  blockedGate?: string | null
  finalVideoUrl?: string
  canWrite: boolean
  onGraphUpdated: (snapshot: any) => void
}

export const StoryGraphStudioPanel = ({
  productionId,
  storyGraph,
  currentStage,
  pipelineStatus,
  pipelineError,
  blockedGate,
  finalVideoUrl,
  canWrite,
  onGraphUpdated,
}: StoryGraphStudioPanelProps) => {
  const [activeStep, setActiveStep] = useState<ActiveStepId>('s3_images')
  const [expandAllSteps, setExpandAllSteps] = useState<boolean>(false)
  const [show3DGraph, setShow3DGraph] = useState<boolean>(false)
  const [showMasterCutBanner, setShowMasterCutBanner] = useState<boolean>(true)
  const [designFilter, setDesignFilter] = useState<'all' | 'character' | 'location' | 'object'>('all')
  const [isRunningPipeline, setIsRunningPipeline] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [gateNotes, setGateNotes] = useState<Record<string, string>>({})
  const [compiledPreviews, setCompiledPreviews] = useState<Record<string, any>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [selectedItem, setSelectedItem] = useState<SelectedInspectorItem | null>(null)

  const stageRuns = storyGraph?.stage_runs || []
  const completedStages = new Set(
    stageRuns.filter((sr: any) => sr.completed).map((sr: any) => sr.stage),
  )
  const latestStageRunByStage: Record<string, any> = {}
  for (const sr of stageRuns) {
    latestStageRunByStage[sr.stage] = sr
  }
  const failedStageRuns = Object.values(latestStageRunByStage).filter(
    (sr: any) => sr.status === 'failed' || sr.error,
  )

  const gatesById: Record<string, any> = {}
  for (const g of storyGraph?.gates || []) {
    gatesById[g.gate_id] = g
  }

  const pendingGate =
    blockedGate ||
    (['G1', 'G2', 'G3'].find((gid) => gatesById[gid]?.decision === 'pending') ?? null)

  const activeError =
    errorMsg ||
    (pipelineStatus === 'failed' ? pipelineError || 'Pipeline execution failed' : null) ||
    (failedStageRuns.length > 0
      ? `Stage ${failedStageRuns[failedStageRuns.length - 1].stage} failed: ${failedStageRuns[failedStageRuns.length - 1].error}`
      : null)

  const characters = storyGraph?.entities?.characters || []
  const locations = storyGraph?.entities?.locations || []
  const objects = storyGraph?.entities?.objects || []
  const entityMap: Record<string, any> = {}
  for (const e of storyGraph?.entities?.all || []) {
    entityMap[e.id] = e
  }

  const scenes = storyGraph?.scenes || []
  const appearances = (storyGraph?.appearances || []).filter((a: any) => a.status !== 'superseded')
  const approvedAppearancesCount = appearances.filter((a: any) => a.status === 'approved').length
  const filteredAppearances = appearances.filter((a: any) => {
    if (designFilter === 'all') return true
    const ent = entityMap[a.entity_id]
    return ent?.entity_type === designFilter
  })

  const allAssets = storyGraph?.assets || []
  const assetsById: Record<string, any> = {}
  for (const a of allAssets) {
    assetsById[a.id] = a
  }
  const auxiliaryAssets = allAssets.filter(
    (a: any) => a.kind === 'composite_sheet' || a.kind === 'first_frame',
  )

  const shots = storyGraph?.shots || []
  const events = storyGraph?.events || []
  const stateFacts = storyGraph?.state_facts || []
  const dialogueLines = storyGraph?.dialogue_lines || []
  const musicCues = storyGraph?.music_cues || []
  const validationIssues = storyGraph?.validation_issues || []
  const changeRequests = storyGraph?.change_requests || []
  const auditLog = storyGraph?.audit_log || []
  const generationRuns = storyGraph?.generation_runs || []
  const latestRunByShotId: Record<string, any> = {}
  for (const r of generationRuns) {
    if (!latestRunByShotId[r.shot_id] || r.attempt >= latestRunByShotId[r.shot_id].attempt) {
      latestRunByShotId[r.shot_id] = r
    }
  }
  const activeGenerationRuns = Object.values(latestRunByShotId)
  const styleGuide = storyGraph?.style_guide

  const macroStepCards = useMemo(
    () => [
      {
        id: 's1_world' as ActiveStepId,
        stepNum: 'STEP 01',
        stages: ['S1_EXTRACT'],
        primaryStage: 'S1_EXTRACT',
        title: 'World Bible & Entities',
        subtitle: 'STORY_ARCHITECT + SUPERVISOR',
        icon: User,
        gate: 'G1' as const,
        metricPrimary: `${characters.length + locations.length + objects.length} Canonical Entities`,
        metricSecondary: `${characters.length} Chars · ${locations.length} Locs · ${objects.length} Props · ${events.length} Events`,
        summaryText:
          styleGuide?.visual_medium ||
          'Canonical characters, locations, hero objects, and state transitions.',
      },
      {
        id: 's2_scripts' as ActiveStepId,
        stepNum: 'STEP 02',
        stages: ['S2_SCREENPLAY'],
        primaryStage: 'S2_SCREENPLAY',
        title: 'Screenplay & Dialogue',
        subtitle: 'SCREENWRITER AGENT',
        icon: FileText,
        metricPrimary: `${scenes.length} Scenes · ${dialogueLines.length} Lines`,
        metricSecondary: `Structured scene scripts & character dialogue`,
        summaryText:
          scenes[0]?.summary ||
          'Scene-by-scene action summaries and lip-synced character dialogue.',
      },
      {
        id: 's3_images' as ActiveStepId,
        stepNum: 'STEP 03',
        stages: ['S3_DESIGN'],
        primaryStage: 'S3_DESIGN',
        title: 'Visual Reference Sheets',
        subtitle: 'CHAR / LOC / OBJ DESIGNERS',
        icon: Sparkles,
        gate: 'G2' as const,
        metricPrimary: `${appearances.length} Reference Images`,
        metricSecondary: `${approvedAppearancesCount}/${appearances.length} Approved · ${auxiliaryAssets.length} Composites`,
        summaryText:
          'Canonical character sheets, location plates, and hero props evaluated by CRITIC VLM.',
      },
      {
        id: 's4_s5_shots' as ActiveStepId,
        stepNum: 'STEP 04',
        stages: ['S4_SHOTS', 'S5_MUSIC'],
        primaryStage: 'S4_SHOTS',
        title: 'Shot Breakdown & Music',
        subtitle: 'DIRECTOR + MUSIC_DIRECTOR',
        icon: Film,
        gate: 'G3' as const,
        metricPrimary: `${shots.length} Directed Shots`,
        metricSecondary: `${musicCues.length} Music Cues · Camera & Continuity Locks`,
        summaryText:
          'Timed ActionBeats, lens & framing specs, start-frame continuity links, and audio cues.',
      },
      {
        id: 's6_s7_compile' as ActiveStepId,
        stepNum: 'STEP 05',
        stages: ['S6_VALIDATE', 'S7_COMPILE'],
        primaryStage: 'S7_COMPILE',
        title: 'Validator & Compiler',
        subtitle: 'VALIDATOR V1–V13 + JINJA2',
        icon: ShieldCheck,
        metricPrimary:
          validationIssues.length === 0
            ? 'All V1–V13 Checks Passed'
            : `${validationIssues.length} Validation Alerts`,
        metricSecondary: `${auditLog.length} Graph Mutations Audited`,
        summaryText:
          'Deterministic continuity invariants, reference image budgeting, and Jinja2 prompt compilation.',
      },
      {
        id: 's8_s10_videos' as ActiveStepId,
        stepNum: 'STEP 06',
        stages: ['S8_RENDER', 'S9_QA', 'S10_ASSEMBLE'],
        primaryStage: 'S8_RENDER',
        title: 'Video Clips & Final Cut',
        subtitle: 'GEMINI OMNI / VEO + FFMPEG',
        icon: Play,
        metricPrimary: `${activeGenerationRuns.length}/${shots.length} Video Clips`,
        metricSecondary: finalVideoUrl ? 'Master Final Cut Stitched' : 'Awaiting Final Cut Render',
        summaryText:
          'Reference-conditioned video clips, start/end continuity frames, VLM QA, and stitched master cut.',
      },
    ],
    [
      characters.length,
      locations.length,
      objects.length,
      events.length,
      styleGuide,
      scenes,
      dialogueLines.length,
      appearances.length,
      approvedAppearancesCount,
      auxiliaryAssets.length,
      shots.length,
      musicCues.length,
      validationIssues.length,
      auditLog.length,
      activeGenerationRuns.length,
      finalVideoUrl,
    ],
  )

  const handleRunForward = async (autoApprove = false) => {
    setIsRunningPipeline(true)
    setErrorMsg(null)
    try {
      const snap = await api.projects.runStoryGraph(productionId, {
        auto_approve_gates: autoApprove ? true : undefined,
      })
      onGraphUpdated(snap)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Pipeline execution failed')
    } finally {
      setIsRunningPipeline(false)
    }
  }

  const handleRunStage = async (stageId: string) => {
    setBusyAction(stageId)
    setErrorMsg(null)
    try {
      const snap = await api.projects.runStage(productionId, stageId)
      onGraphUpdated(snap)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : `Stage ${stageId} failed`)
    } finally {
      setBusyAction(null)
    }
  }

  const handleGateDecision = async (gateId: 'G1' | 'G2' | 'G3', decision: 'approve' | 'reject') => {
    setBusyAction(`gate_${gateId}_${decision}`)
    setErrorMsg(null)
    try {
      const note = gateNotes[gateId]
      const snap =
        decision === 'approve'
          ? await api.projects.approveGate(productionId, gateId, note || undefined)
          : await api.projects.rejectGate(productionId, gateId, note || undefined)
      setGateNotes((prev) => ({ ...prev, [gateId]: '' }))
      onGraphUpdated(snap)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : `Gate ${gateId} ${decision} failed`)
    } finally {
      setBusyAction(null)
    }
  }

  const handleAppearanceAction = async (appearanceId: string, action: 'approve' | 'regenerate') => {
    setBusyAction(`app_${appearanceId}_${action}`)
    setErrorMsg(null)
    try {
      const snap =
        action === 'approve'
          ? await api.projects.approveAppearance(productionId, appearanceId)
          : await api.projects.regenerateAppearance(productionId, appearanceId)
      onGraphUpdated(snap)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Appearance action failed')
    } finally {
      setBusyAction(null)
    }
  }

  const handleCompilePreview = async (shotId: string) => {
    setBusyAction(`compile_${shotId}`)
    setErrorMsg(null)
    try {
      const res = await api.projects.compileShot(productionId, shotId)
      setCompiledPreviews((prev) => ({ ...prev, [shotId]: res }))
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Shot compilation preview failed')
    } finally {
      setBusyAction(null)
    }
  }

  const renderGateControlBar = (gateId: 'G1' | 'G2' | 'G3', stageId: string, stageLabel: string) => {
    const gate = gatesById[gateId]
    const decision = gate?.decision || 'pending'
    return (
      <div
        className={cn(
          'rounded-xl border p-4 flex flex-wrap items-center justify-between gap-3',
          decision === 'approved'
            ? 'bg-emerald-500/10 border-emerald-500/30'
            : decision === 'rejected'
              ? 'bg-red-500/10 border-red-500/30'
              : 'bg-amber-500/10 border-amber-500/40',
        )}
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <span
            className={cn(
              'px-2.5 py-0.5 rounded text-[11px] font-mono font-bold uppercase',
              decision === 'approved'
                ? 'bg-emerald-500/20 text-emerald-400'
                : decision === 'rejected'
                  ? 'bg-red-500/20 text-red-400'
                  : 'bg-amber-500/20 text-amber-400',
            )}
          >
            Gate {gateId}: {decision}
          </span>
          <span className="text-xs font-medium text-foreground">
            Review {stageLabel} outputs — approve to unlock downstream stages, reject, or regenerate{' '}
            {stageId}.
          </span>
        </div>

        {canWrite && (
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={gateNotes[gateId] || ''}
              onChange={(e) => setGateNotes((prev) => ({ ...prev, [gateId]: e.target.value }))}
              placeholder={`Reviewer notes for ${gateId}...`}
              className="h-8 text-xs w-48 bg-card border-border"
            />
            <Button
              size="xs"
              variant="primary"
              icon={busyAction === `gate_${gateId}_approve` ? Loader2 : CheckCircle2}
              onClick={() => handleGateDecision(gateId, 'approve')}
              disabled={!!busyAction || isRunningPipeline}
            >
              Approve {gateId}
            </Button>
            <Button
              size="xs"
              variant="outline"
              icon={busyAction === `gate_${gateId}_reject` ? Loader2 : XCircle}
              onClick={() => handleGateDecision(gateId, 'reject')}
              disabled={!!busyAction || isRunningPipeline}
            >
              Reject {gateId}
            </Button>
            <Button
              size="xs"
              variant="ghost"
              icon={busyAction === stageId ? Loader2 : RefreshCw}
              onClick={() => handleRunStage(stageId)}
              disabled={!!busyAction || isRunningPipeline}
            >
              Regenerate {stageId}
            </Button>
          </div>
        )}
      </div>
    )
  }

  const isStepVisible = (stepId: ActiveStepId) => expandAllSteps || activeStep === stepId

  return (
    <div className="space-y-6 w-full">
      {/* STRICT FAILURE BANNER (Zero Silent Fallbacks) */}
      {activeError && (
        <div className="rounded-xl border-2 border-red-500/60 bg-red-500/15 p-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <AlertTriangle size={20} className="text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-red-500/30 text-red-200 text-[10px] font-mono font-bold uppercase">
                  Pipeline Halted — Strict Failure Mode (No Silent Fallback)
                </span>
                {currentStage && (
                  <span className="text-[11px] font-mono text-red-300">Stage: {currentStage}</span>
                )}
              </div>
              <p className="text-xs font-mono text-red-200 break-all">{activeError}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {canWrite && currentStage && (
              <Button
                size="xs"
                variant="primary"
                icon={busyAction === currentStage ? Loader2 : RefreshCw}
                onClick={() => handleRunStage(currentStage)}
                disabled={!!busyAction || isRunningPipeline}
              >
                Retry {currentStage}
              </Button>
            )}
            <Button variant="ghost" size="xs" onClick={() => setErrorMsg(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* TOP COMMAND HEADER & LARGE PIPELINE STEP CARDS (PROGRESSIVE DISCLOSURE)*/}
      {/* ===================================================================== */}
      <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent-dark">
              <GitBranch size={18} />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-heading font-bold uppercase tracking-wider text-foreground">
                  Story-to-Video Pipeline Stages
                </h3>
                <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[11px] font-mono font-bold">
                  {completedStages.size - (completedStages.has('S0_INGEST') ? 1 : 0)}/10 Stages
                  Complete
                </span>
                {pendingGate && (
                  <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 text-[11px] font-mono font-bold">
                    Awaiting Gate {pendingGate} Approval
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                Select any pipeline step card below to inspect its intermediate outputs, or click an
                artifact to view deep telemetry in the right inspector pane.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="xs"
              variant={show3DGraph ? 'secondary' : 'outline'}
              icon={Orbit}
              onClick={() => setShow3DGraph((v) => !v)}
            >
              {show3DGraph ? 'Hide 3D Constellation' : '3D StoryGraph View'}
            </Button>
            <Button
              size="xs"
              variant={expandAllSteps ? 'secondary' : 'outline'}
              icon={Layers}
              onClick={() => setExpandAllSteps((v) => !v)}
            >
              {expandAllSteps ? 'Focused Step Mode' : 'Expand All Stages'}
            </Button>
            {canWrite && (
              <>
                <Button
                  size="xs"
                  variant="outline"
                  icon={isRunningPipeline ? Loader2 : Play}
                  onClick={() => handleRunForward(false)}
                  disabled={isRunningPipeline || !!busyAction}
                >
                  {isRunningPipeline ? 'Running Step...' : 'Step Mode (Next Gate)'}
                </Button>
                <Button
                  size="xs"
                  variant="primary"
                  icon={isRunningPipeline ? Loader2 : Sparkles}
                  onClick={() => handleRunForward(true)}
                  disabled={isRunningPipeline || !!busyAction}
                >
                  {isRunningPipeline
                    ? 'Auto-Running Pipeline...'
                    : 'Auto Mode (Auto-Approve All & Final Cut)'}
                </Button>
              </>
            )}
          </div>
        </div>

        {/* LARGE PIPELINE STEP CARDS (6 Macro-Steps covering S1..S10) */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6 gap-3.5">
          {macroStepCards.map((card) => {
            const Icon = card.icon
            const isSelected = !expandAllSteps && activeStep === card.id
            const allDone = card.stages.every((st) => completedStages.has(st))
            const anyFailed = card.stages.some(
              (st) =>
                latestStageRunByStage[st]?.status === 'failed' ||
                !!latestStageRunByStage[st]?.error,
            )
            const gateObj = card.gate ? gatesById[card.gate] : null

            return (
              <div
                key={card.id}
                onClick={() => {
                  setExpandAllSteps(false)
                  setActiveStep(card.id)
                  setSelectedItem({
                    kind: 'stage',
                    id: card.primaryStage,
                    data: card,
                  })
                }}
                className={cn(
                  'cursor-pointer rounded-xl border p-4 transition-all flex flex-col justify-between gap-3 relative overflow-hidden group',
                  anyFailed
                    ? 'bg-red-500/15 border-red-500/60 hover:border-red-400'
                    : isSelected
                      ? 'ring-2 ring-accent bg-accent/15 border-accent shadow-lg'
                      : allDone
                        ? 'bg-card/90 border-emerald-500/35 hover:border-emerald-500/70 hover:bg-card'
                        : 'bg-card/50 border-border/70 hover:border-accent/50',
                )}
              >
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <div
                        className={cn(
                          'w-8 h-8 rounded-lg flex items-center justify-center border',
                          anyFailed
                            ? 'bg-red-500/20 border-red-500/40 text-red-300'
                            : isSelected
                              ? 'bg-accent/25 border-accent/50 text-accent-dark'
                              : allDone
                                ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400'
                                : 'bg-muted border-border text-muted-foreground',
                        )}
                      >
                        <Icon size={16} />
                      </div>
                      <div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                            {card.stepNum}
                          </span>
                          <span className="text-[10px] font-mono text-accent-dark font-bold">
                            ({card.stages.join('·')})
                          </span>
                        </div>
                        <h4 className="text-sm font-heading font-bold text-foreground leading-tight">
                          {card.title}
                        </h4>
                      </div>
                    </div>

                    {anyFailed ? (
                      <AlertTriangle size={16} className="text-red-400 shrink-0" />
                    ) : allDone ? (
                      <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                    ) : (
                      <Clock size={15} className="text-muted-foreground shrink-0" />
                    )}
                  </div>

                  <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">
                    {card.summaryText}
                  </p>
                </div>

                <div className="pt-2.5 border-t border-border/50 space-y-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-mono font-bold text-foreground">
                      {card.metricPrimary}
                    </span>
                    {card.gate && (
                      <span
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[9px] font-mono font-bold uppercase',
                          gateObj?.decision === 'approved'
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : gateObj?.decision === 'rejected'
                              ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                              : 'bg-amber-500/20 text-amber-300 border border-amber-500/30',
                        )}
                      >
                        Gate {card.gate}: {gateObj?.decision || 'pending'}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground">
                    <span className="truncate">{card.metricSecondary}</span>
                    <ChevronRight
                      size={13}
                      className={cn(
                        'shrink-0 transition-transform',
                        isSelected ? 'translate-x-0.5 text-accent-dark' : 'group-hover:translate-x-0.5',
                      )}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* OPTIONAL 3D FORCE-DIRECTED CONSTELLATION DRAWER */}
      {show3DGraph && (
        <StoryGraphVisualizer3D
          storyGraph={storyGraph}
          canWrite={canWrite}
          onApproveAppearance={(appId) => handleAppearanceAction(appId, 'approve')}
          onRegenerateAppearance={(appId) => handleAppearanceAction(appId, 'regenerate')}
        />
      )}

      {/* ===================================================================== */}
      {/* TWO-PANE WORKSPACE: MAIN STAGE CANVAS (LEFT) + INSPECTOR PANE (RIGHT) */}
      {/* ===================================================================== */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        {/* LEFT / MAIN PROGRESSIVE DISCLOSURE CANVAS (8 Cols on XL) */}
        <div className="xl:col-span-8 space-y-6">
          {/* Quick Master Final Cut Collapsible Player if Ready */}
          {finalVideoUrl && activeStep !== 's8_s10_videos' && (
            <div className="glass rounded-xl p-4 border border-emerald-500/30 bg-emerald-500/5 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 text-[10px] font-mono font-bold uppercase">
                    Master Final Cut Ready
                  </span>
                  <span className="text-xs font-semibold text-foreground">
                    Stitched {activeGenerationRuns.length}-Clip Master Output (S10_ASSEMBLE)
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="xs"
                    variant="outline"
                    icon={Film}
                    onClick={() => setActiveStep('s8_s10_videos')}
                  >
                    Inspect All {activeGenerationRuns.length} Clips
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    icon={showMasterCutBanner ? ChevronDown : ChevronRight}
                    onClick={() => setShowMasterCutBanner((v) => !v)}
                  >
                    {showMasterCutBanner ? 'Minimize Player' : 'Show Player'}
                  </Button>
                </div>
              </div>
              {showMasterCutBanner && (
                <div className="aspect-video max-w-3xl mx-auto rounded-xl overflow-hidden bg-black border border-border">
                  <video
                    key={finalVideoUrl}
                    controls
                    preload="metadata"
                    src={finalVideoUrl}
                    className="w-full h-full"
                  />
                </div>
              )}
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 1: WORLD BIBLE, ENTITIES & CONTINUITY TIMELINE (S1_EXTRACT)  */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s1_world') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 01 · S1_EXTRACT
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      World Bible, Canonical Entities & Continuity Timeline
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Click any Character, Location, or Object card to inspect its attributes,
                    provenance, and linked reference sheets in the right pane.
                  </p>
                </div>
                {canWrite && (
                  <Button
                    size="xs"
                    variant="outline"
                    icon={busyAction === 'S1_EXTRACT' ? Loader2 : RefreshCw}
                    onClick={() => handleRunStage('S1_EXTRACT')}
                    disabled={!!busyAction || isRunningPipeline}
                  >
                    Regenerate Stage S1
                  </Button>
                )}
              </div>

              {renderGateControlBar('G1', 'S1_EXTRACT', 'World Bible & Canonical Entities')}

              {styleGuide && (
                <Card title="Global StyleGuide (STORY_ARCHITECT)" icon={Sparkles}>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
                      <span className="text-[10px] font-bold uppercase text-muted-foreground">
                        Visual Medium
                      </span>
                      <p className="font-medium mt-1 text-foreground">{styleGuide.visual_medium}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
                      <span className="text-[10px] font-bold uppercase text-muted-foreground">
                        Lens & Camera Language
                      </span>
                      <p className="font-medium mt-1 text-foreground">{styleGuide.lens_language}</p>
                    </div>
                    <div className="p-3 rounded-lg bg-muted/30 border border-border/50">
                      <span className="text-[10px] font-bold uppercase text-muted-foreground">
                        Lighting Rules
                      </span>
                      <p className="font-medium mt-1 text-foreground">
                        {styleGuide.lighting_rules}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-border/50">
                    <span className="text-[10px] font-bold uppercase text-muted-foreground">
                      Color Palette:
                    </span>
                    {(styleGuide.palette || []).map((c: string) => (
                      <span
                        key={c}
                        className="px-2 py-0.5 rounded bg-accent/10 text-accent-dark text-[10px] font-mono"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </Card>
              )}

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[
                  { title: 'Characters', items: characters, icon: User },
                  { title: 'Locations', items: locations, icon: MapPin },
                  { title: 'Objects / Hero Props', items: objects, icon: Box },
                ].map((group) => (
                  <Card
                    key={group.title}
                    title={`${group.title} (${group.items.length})`}
                    icon={group.icon}
                  >
                    <div className="space-y-2.5">
                      {group.items.map((ent: any) => {
                        const entApps = appearances.filter((a: any) => a.entity_id === ent.id)
                        const thumbUrl = entApps[0]?.assets?.[entApps[0]?.assets.length - 1]?.signed_url
                        const isSelected =
                          selectedItem?.kind === 'entity' && selectedItem?.id === ent.id
                        return (
                          <div
                            key={ent.id}
                            onClick={() =>
                              setSelectedItem({
                                kind: 'entity',
                                id: ent.id,
                                data: ent,
                              })
                            }
                            className={cn(
                              'cursor-pointer p-3 rounded-xl border transition-all flex items-center gap-3',
                              isSelected
                                ? 'ring-2 ring-accent bg-accent/15 border-accent'
                                : 'bg-muted/40 border-border/60 hover:border-accent/50',
                            )}
                          >
                            {thumbUrl ? (
                              <img
                                src={thumbUrl}
                                alt={ent.canonical_name}
                                className="w-12 h-12 rounded-lg object-cover border border-border shrink-0"
                              />
                            ) : (
                              <div className="w-12 h-12 rounded-lg bg-muted flex items-center justify-center text-muted-foreground shrink-0">
                                <group.icon size={18} />
                              </div>
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-xs font-bold text-foreground truncate">
                                  {ent.canonical_name}
                                </span>
                                <span className="text-[9px] font-mono text-muted-foreground shrink-0">
                                  {ent.id}
                                </span>
                              </div>
                              <p className="text-[10px] text-muted-foreground truncate mt-0.5">
                                {Object.keys(ent.attributes || {}).length} attributes ·{' '}
                                {entApps.length} ref sheets
                              </p>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </Card>
                ))}
              </div>

              <Card
                title={`Narrative Event Timeline & State Transitions (${events.length} Events · ${stateFacts.length} StateFacts)`}
                icon={History}
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  {events.map((ev: any) => (
                    <div
                      key={ev.id}
                      className="p-3 rounded-lg bg-muted/30 border border-border/50 space-y-1.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold">
                          Event #{ev.story_order} · {ev.scene_id}
                        </span>
                        <span className="text-[10px] font-mono text-muted-foreground">{ev.id}</span>
                      </div>
                      <p className="text-xs font-medium text-foreground">{ev.summary}</p>
                      {(ev.effects || []).length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-1">
                          {ev.effects.map((eff: any, i: number) => (
                            <span
                              key={i}
                              className="px-1.5 py-0.5 rounded bg-card border border-border text-[9px] font-mono text-emerald-400"
                            >
                              {eff.entity_id}.{eff.attribute} → {eff.new_value ?? 'null'}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 2: SCREENPLAY & SCENE DIALOGUE SCRIPTS (S2_SCREENPLAY)       */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s2_scripts') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 02 · S2_SCREENPLAY
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      Screenplay & Scene Dialogue Scripts ({scenes.length} Scenes ·{' '}
                      {dialogueLines.length} Dialogue Lines)
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Click any scene card to inspect its full action beats, location plate, and
                    dialogue breakdown in the right details pane.
                  </p>
                </div>
                {canWrite && (
                  <Button
                    size="xs"
                    variant="outline"
                    icon={busyAction === 'S2_SCREENPLAY' ? Loader2 : RefreshCw}
                    onClick={() => handleRunStage('S2_SCREENPLAY')}
                    disabled={!!busyAction || isRunningPipeline}
                  >
                    Regenerate Screenplay (S2)
                  </Button>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {scenes.map((sc: any) => {
                  const scEvents = events.filter((e: any) => e.scene_id === sc.id)
                  const scDialogues = dialogueLines.filter(
                    (dl: any) => dl.id.includes(sc.id) || (dl.shot_id && dl.shot_id.includes(sc.id)),
                  )
                  const loc = entityMap[sc.location_id]
                  const isSelected =
                    selectedItem?.kind === 'scene' && selectedItem?.id === sc.id
                  return (
                    <div
                      key={sc.id}
                      onClick={() =>
                        setSelectedItem({
                          kind: 'scene',
                          id: sc.id,
                          data: { scene: sc, events: scEvents, dialogues: scDialogues, loc },
                        })
                      }
                      className={cn(
                        'cursor-pointer rounded-xl p-4 border transition-all space-y-3',
                        isSelected
                          ? 'ring-2 ring-accent bg-accent/10 border-accent'
                          : 'bg-card/70 border-border/70 hover:border-accent/50',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[11px] font-mono font-bold">
                          Scene {sc.index}: {sc.id}
                        </span>
                        <span className="text-[10px] font-mono text-muted-foreground">
                          {loc?.canonical_name || sc.location_id} · {sc.time_of_day}
                        </span>
                      </div>
                      <h4 className="text-sm font-bold text-foreground">
                        {sc.heading || `${loc?.canonical_name || sc.location_id}`}
                      </h4>
                      <p className="text-xs text-muted-foreground leading-relaxed">{sc.summary}</p>

                      <div className="space-y-1.5 pt-2 border-t border-border/50">
                        <span className="text-[10px] font-bold uppercase text-muted-foreground">
                          Dialogue Lines ({scDialogues.length})
                        </span>
                        {scDialogues.map((dl: any) => {
                          const speaker = entityMap[dl.speaker_id]
                          return (
                            <div
                              key={dl.id}
                              className="p-2.5 rounded-lg bg-muted/40 border border-border/60 space-y-1"
                            >
                              <div className="flex items-center justify-between text-[10px] font-mono">
                                <span className="font-bold text-accent-dark uppercase">
                                  {speaker?.canonical_name || dl.speaker_id}
                                </span>
                                <span className="text-muted-foreground">
                                  {dl.delivery} · {dl.emotion}
                                </span>
                              </div>
                              <p className="text-xs italic text-foreground">"{dl.text}"</p>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 3: VISUAL DESIGN REFERENCE IMAGES (S3_DESIGN · GATE G2)      */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s3_images') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 03 · S3_DESIGN
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      Visual Design Studio — Character, Location & Prop Reference Images
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Click any reference sheet card to inspect high-res artwork, CRITIC VLM QA
                    telemetry, and Approve/Regenerate controls in the right pane.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {[
                    { id: 'all', label: `All (${appearances.length})` },
                    { id: 'character', label: 'Characters' },
                    { id: 'location', label: 'Locations' },
                    { id: 'object', label: 'Objects / Props' },
                  ].map((f) => (
                    <Button
                      key={f.id}
                      size="xs"
                      variant={designFilter === f.id ? 'primary' : 'outline'}
                      onClick={() => setDesignFilter(f.id as any)}
                    >
                      {f.label}
                    </Button>
                  ))}
                  {canWrite && (
                    <Button
                      size="xs"
                      variant="outline"
                      icon={busyAction === 'S3_DESIGN' ? Loader2 : RefreshCw}
                      onClick={() => handleRunStage('S3_DESIGN')}
                      disabled={!!busyAction || isRunningPipeline}
                    >
                      Regenerate All Sheets (S3)
                    </Button>
                  )}
                </div>
              </div>

              {renderGateControlBar(
                'G2',
                'S3_DESIGN',
                'Character, Location & Object Reference Sheets',
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
                {filteredAppearances.map((appNode: any) => {
                  const ent = entityMap[appNode.entity_id]
                  const asset = appNode.assets?.[appNode.assets.length - 1]
                  const isSelected =
                    selectedItem?.kind === 'appearance' && selectedItem?.id === appNode.id
                  return (
                    <div
                      key={appNode.id}
                      onClick={() =>
                        setSelectedItem({
                          kind: 'appearance',
                          id: appNode.id,
                          data: { appearance: appNode, entity: ent, asset },
                        })
                      }
                      className={cn(
                        'cursor-pointer rounded-xl overflow-hidden border transition-all flex flex-col justify-between',
                        isSelected
                          ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg'
                          : 'bg-card/80 border-border/70 hover:border-accent/50',
                      )}
                    >
                      <div>
                        <div className="aspect-video bg-muted relative overflow-hidden">
                          {asset?.signed_url ? (
                            <img
                              src={asset.signed_url}
                              alt={appNode.id}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">
                              No reference image generated yet
                            </div>
                          )}
                          <div className="absolute top-2 left-2 flex items-center gap-1">
                            <span className="px-2 py-0.5 rounded bg-black/75 text-white text-[9px] font-mono uppercase">
                              {ent?.entity_type || 'entity'} · v{appNode.version}
                            </span>
                            <span className="px-2 py-0.5 rounded bg-black/75 text-amber-300 text-[9px] font-mono">
                              {appNode.state_label}
                            </span>
                          </div>
                          <div className="absolute top-2 right-2">
                            <span
                              className={cn(
                                'px-2 py-0.5 rounded text-[9px] font-mono font-bold uppercase',
                                appNode.status === 'approved'
                                  ? 'bg-emerald-500/90 text-white'
                                  : 'bg-amber-500/90 text-black',
                              )}
                            >
                              {appNode.status}
                            </span>
                          </div>
                        </div>

                        <div className="p-4 space-y-2">
                          <div className="flex items-center justify-between">
                            <h5 className="text-sm font-bold text-foreground">
                              {ent?.canonical_name || appNode.entity_id}
                            </h5>
                            <span className="text-[9px] font-mono text-muted-foreground">
                              {appNode.id}
                            </span>
                          </div>
                          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                            {appNode.visual_description}
                          </p>
                        </div>
                      </div>

                      {canWrite && (
                        <div
                          className="px-4 pb-3.5 pt-2 border-t border-border/40 flex items-center justify-between gap-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <span className="text-[10px] font-mono text-muted-foreground">
                            Click card for VLM QA
                          </span>
                          <div className="flex items-center gap-1.5">
                            {appNode.status !== 'approved' && (
                              <Button
                                size="xs"
                                variant="primary"
                                icon={CheckCircle2}
                                onClick={() => handleAppearanceAction(appNode.id, 'approve')}
                                disabled={!!busyAction}
                              >
                                Approve
                              </Button>
                            )}
                            <Button
                              size="xs"
                              variant="outline"
                              icon={RefreshCw}
                              onClick={() => handleAppearanceAction(appNode.id, 'regenerate')}
                              disabled={!!busyAction}
                            >
                              Regen
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 4: SHOT BREAKDOWN & MUSIC CUES (S4_SHOTS + S5_MUSIC · G3)    */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s4_s5_shots') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 04 · S4_SHOTS + S5_MUSIC
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      Director Shot Breakdown, Camera Continuity & Music/SFX Cues
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Click any shot card to inspect its timed ActionBeats, cast appearances, and
                    compiled Jinja2 prompt in the right pane.
                  </p>
                </div>
                {canWrite && (
                  <div className="flex items-center gap-2">
                    <Button
                      size="xs"
                      variant="outline"
                      icon={busyAction === 'S4_SHOTS' ? Loader2 : RefreshCw}
                      onClick={() => handleRunStage('S4_SHOTS')}
                      disabled={!!busyAction || isRunningPipeline}
                    >
                      Regenerate Shots (S4)
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      icon={busyAction === 'S5_MUSIC' ? Loader2 : RefreshCw}
                      onClick={() => handleRunStage('S5_MUSIC')}
                      disabled={!!busyAction || isRunningPipeline}
                    >
                      Regenerate Music (S5)
                    </Button>
                  </div>
                )}
              </div>

              {renderGateControlBar('G3', 'S4_SHOTS', 'Director Shot Breakdown & Music Cues')}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {shots.map((sh: any) => {
                  const shotDialogues = dialogueLines.filter(
                    (dl: any) => (sh.dialogue_ids || []).includes(dl.id) || dl.shot_id === sh.id,
                  )
                  const cue = musicCues.find((m: any) => m.id === sh.music_cue_id)
                  const isSelected = selectedItem?.kind === 'shot' && selectedItem?.id === sh.id
                  return (
                    <div
                      key={sh.id}
                      onClick={() =>
                        setSelectedItem({
                          kind: 'shot',
                          id: sh.id,
                          data: { shot: sh, dialogues: shotDialogues, cue },
                        })
                      }
                      className={cn(
                        'cursor-pointer rounded-xl p-4 border transition-all space-y-3',
                        isSelected
                          ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg'
                          : 'bg-card/80 border-border/70 hover:border-accent/50',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                            {sh.id}
                          </span>
                          <span className="text-xs font-mono text-muted-foreground">
                            #{sh.story_order} · {sh.duration_s}s · {sh.camera?.shot_size} ·{' '}
                            {sh.camera?.lens_mm}mm
                          </span>
                        </div>
                        {sh.continue_from_last_frame && (
                          <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 text-[9px] font-mono">
                            Frame Continuity
                          </span>
                        )}
                      </div>

                      <div className="space-y-1.5 text-xs">
                        {(sh.beats || []).map((b: any, idx: number) => (
                          <div
                            key={idx}
                            className="p-2 rounded bg-muted/40 border border-border/50"
                          >
                            <span className="font-mono text-accent-dark mr-1.5">
                              ({b.t_start_s.toFixed(1)}–{b.t_end_s.toFixed(1)}s)
                            </span>
                            <span>{b.description}</span>
                          </div>
                        ))}
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/40 text-[10px] font-mono text-muted-foreground">
                        <span>
                          {(sh.cast || []).length} Cast · {shotDialogues.length} Dialogue Lines
                        </span>
                        {cue && (
                          <span className="flex items-center gap-1 text-accent-dark">
                            <Music size={11} /> {cue.mood}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 5: VALIDATOR V1-V13 & PROMPT COMPILER (S6 + S7)              */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s6_s7_compile') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 05 · S6_VALIDATE + S7_COMPILE
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      Deterministic Continuity Validator (V1–V13) & Jinja2 Prompt Compiler
                    </h3>
                  </div>
                </div>
                {canWrite && (
                  <div className="flex items-center gap-2">
                    <Button
                      size="xs"
                      variant="outline"
                      icon={busyAction === 'S6_VALIDATE' ? Loader2 : ShieldCheck}
                      onClick={() => handleRunStage('S6_VALIDATE')}
                      disabled={!!busyAction || isRunningPipeline}
                    >
                      Run Validator (S6)
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      icon={busyAction === 'S7_COMPILE' ? Loader2 : Terminal}
                      onClick={() => handleRunStage('S7_COMPILE')}
                      disabled={!!busyAction || isRunningPipeline}
                    >
                      Compile All Prompts (S7)
                    </Button>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Card
                  title={`Continuity Invariants V1–V13 (${validationIssues.length} Issues)`}
                  icon={ShieldCheck}
                >
                  {validationIssues.length === 0 ? (
                    <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs text-emerald-400 flex items-center gap-2">
                      <CheckCircle2 size={16} />
                      All V1–V13 continuity, state, asset approval, and speech-rate invariants
                      passed!
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {validationIssues.map((iss, idx) => (
                        <div
                          key={idx}
                          className={cn(
                            'p-2.5 rounded-lg border text-xs flex items-start gap-2',
                            iss.severity === 'error'
                              ? 'bg-red-500/10 border-red-500/30 text-red-300'
                              : 'bg-amber-500/10 border-amber-500/30 text-amber-300',
                          )}
                        >
                          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                          <div>
                            <span className="font-mono font-bold mr-2">
                              [{iss.code}] ({iss.node_id})
                            </span>
                            <span>{iss.message}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {changeRequests.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-border/50 space-y-2">
                      <h5 className="text-xs font-bold uppercase text-muted-foreground">
                        Cross-Role ChangeRequests ({changeRequests.length})
                      </h5>
                      {changeRequests.map((cr: any) => (
                        <div
                          key={cr.id}
                          className="p-2.5 rounded bg-muted/40 border border-border text-xs"
                        >
                          <span className="font-mono font-bold text-accent-dark">
                            {cr.from_role} → {cr.to_role} ({cr.target_node_id}):
                          </span>{' '}
                          {cr.reason}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card
                  title={`Role-Agent Mutation Audit Log (${auditLog.length} Entries)`}
                  icon={Eye}
                >
                  <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
                    {auditLog.map((ae: any) => (
                      <div
                        key={ae.id}
                        className="p-2 rounded bg-muted/30 border border-border/40 text-[11px] flex items-center justify-between gap-2"
                      >
                        <div>
                          <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark font-mono font-bold mr-2">
                            {ae.role}
                          </span>
                          <span className="font-mono text-foreground">{ae.tool}</span>
                          <span className="text-muted-foreground ml-2">
                            → {ae.target_id} (v{ae.after_version})
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          )}

          {/* ----------------------------------------------------------------- */}
          {/* STEP 6: VIDEO CLIP RENDERS & MASTER FINAL CUT (S8..S10)           */}
          {/* ----------------------------------------------------------------- */}
          {isStepVisible('s8_s10_videos') && (
            <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded bg-accent/15 text-accent-dark text-xs font-mono font-bold">
                      STEP 06 · S8_RENDER + S9_QA + S10_ASSEMBLE
                    </span>
                    <h3 className="text-base font-heading font-bold text-foreground">
                      Video Clip Renders, Multimodal VLM QA & Stitched Master Final Cut
                    </h3>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Click any rendered shot clip below to inspect its Start Frame, Reference Sheets,
                    End Frame, VLM QA telemetry, and compiled prompt in the right pane.
                  </p>
                </div>
                {canWrite && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="primary"
                      size="xs"
                      icon={busyAction === 'S8_RENDER' ? Loader2 : RefreshCw}
                      disabled={busyAction !== null || isRunningPipeline || shots.length === 0}
                      onClick={() => handleRunStage('S8_RENDER')}
                    >
                      {generationRuns.length > 0
                        ? 'Re-Render Video Clips (S8)'
                        : 'Render Video Clips (S8)'}
                    </Button>
                    <Button
                      variant="outline"
                      size="xs"
                      icon={busyAction === 'S9_QA' ? Loader2 : ShieldCheck}
                      disabled={
                        busyAction !== null || isRunningPipeline || generationRuns.length === 0
                      }
                      onClick={() => handleRunStage('S9_QA')}
                    >
                      Run Clip QA (S9)
                    </Button>
                    <Button
                      variant="outline"
                      size="xs"
                      icon={busyAction === 'S10_ASSEMBLE' ? Loader2 : Play}
                      disabled={
                        busyAction !== null || isRunningPipeline || generationRuns.length === 0
                      }
                      onClick={() => handleRunStage('S10_ASSEMBLE')}
                    >
                      Stitch Final Cut (S10)
                    </Button>
                  </div>
                )}
              </div>

              {finalVideoUrl ? (
                <Card title="Final Stitched Master Cut (S10_ASSEMBLE)" icon={Play}>
                  <div className="aspect-video max-w-4xl mx-auto rounded-xl overflow-hidden bg-black border border-border">
                    <video
                      key={finalVideoUrl}
                      controls
                      preload="metadata"
                      src={finalVideoUrl}
                      className="w-full h-full"
                    />
                  </div>
                </Card>
              ) : (
                <div className="glass rounded-xl p-6 border border-dashed border-border text-center space-y-3">
                  <Play size={28} className="mx-auto text-muted-foreground" />
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-foreground">
                      Master Final Cut Not Yet Assembled
                    </p>
                    <p className="text-xs text-muted-foreground max-w-md mx-auto">
                      Click "Auto Mode" in the top bar or run S8_RENDER and S10_ASSEMBLE to stitch
                      all clips into the master output.
                    </p>
                  </div>
                </div>
              )}

              {activeGenerationRuns.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {activeGenerationRuns.map((run: any) => {
                    const startAsset = run.first_frame_asset_id
                      ? assetsById[run.first_frame_asset_id]
                      : null
                    const refAssets = (run.reference_asset_ids || [])
                      .map((aid: string) => assetsById[aid])
                      .filter(Boolean)
                    const endAsset = run.extracted_last_frame_asset_id
                      ? assetsById[run.extracted_last_frame_asset_id]
                      : null
                    const isSelected =
                      selectedItem?.kind === 'video_run' && selectedItem?.id === run.id
                    return (
                      <div
                        key={run.id}
                        onClick={() =>
                          setSelectedItem({
                            kind: 'video_run',
                            id: run.id,
                            data: { run, startAsset, refAssets, endAsset },
                          })
                        }
                        className={cn(
                          'cursor-pointer rounded-xl p-4 border transition-all space-y-3',
                          isSelected
                            ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg'
                            : 'bg-card/80 border-border/70 hover:border-accent/50',
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <span className="text-xs font-mono font-bold text-foreground">
                              {run.shot_id} · Attempt #{run.attempt}
                            </span>
                            <span className="text-[10px] font-mono text-muted-foreground ml-2">
                              ({run.model || run.provider})
                            </span>
                          </div>
                          <span
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase',
                              run.status === 'approved'
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : 'bg-amber-500/20 text-amber-400',
                            )}
                          >
                            {run.status}
                          </span>
                        </div>

                        {run.output_video_signed_url && (
                          <div
                            className="aspect-video rounded-lg overflow-hidden bg-black border border-border/60"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <video
                              key={run.output_video_signed_url}
                              controls
                              preload="metadata"
                              src={run.output_video_signed_url}
                              className="w-full h-full"
                            />
                          </div>
                        )}

                        <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground pt-1">
                          <span>
                            {startAsset ? 'Start Frame + ' : ''}
                            {refAssets.length} Refs
                            {endAsset ? ' → End Frame Extracted' : ''}
                          </span>
                          <span className="text-accent-dark font-bold">
                            Inspect Conditioning & QA →
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* =================================================================== */}
        {/* RIGHT STICKY DETAILS & PIPELINE TELEMETRY PANE (4 Cols on XL)       */}
        {/* =================================================================== */}
        <div className="xl:col-span-4 xl:sticky xl:top-4 space-y-4">
          <div className="glass rounded-2xl p-5 border border-border/80 space-y-5">
            <div className="flex items-center justify-between border-b border-border/60 pb-3">
              <div className="flex items-center gap-2">
                <Sliders size={16} className="text-accent-dark" />
                <h4 className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
                  {selectedItem ? `Inspector · ${selectedItem.kind.toUpperCase()}` : 'Pipeline Details & Telemetry'}
                </h4>
              </div>
              {selectedItem && (
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => setSelectedItem(null)}
                >
                  Show Stage Overview
                </Button>
              )}
            </div>

            {/* SELECTED ITEM INSPECTOR */}
            {selectedItem?.kind === 'appearance' && (
              <div className="space-y-4">
                <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border">
                  {selectedItem.data.asset?.signed_url ? (
                    <img
                      src={selectedItem.data.asset.signed_url}
                      alt={selectedItem.id}
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">
                      No image asset
                    </div>
                  )}
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-foreground">
                      {selectedItem.data.entity?.canonical_name ||
                        selectedItem.data.appearance.entity_id}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
                      {selectedItem.data.appearance.state_label} · v
                      {selectedItem.data.appearance.version}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {selectedItem.data.appearance.visual_description}
                  </p>
                  {selectedItem.data.appearance.wardrobe && (
                    <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 text-xs">
                      <span className="text-[10px] font-mono uppercase text-muted-foreground block">
                        Wardrobe / Surface Specs
                      </span>
                      <span className="text-foreground font-medium">
                        {selectedItem.data.appearance.wardrobe}
                      </span>
                    </div>
                  )}
                  {selectedItem.data.asset?.qa_notes && (
                    <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/25 text-xs text-emerald-300 space-y-1">
                      <span className="text-[10px] font-mono font-bold uppercase block">
                        CRITIC VLM Verification
                      </span>
                      <p>{selectedItem.data.asset.qa_notes}</p>
                    </div>
                  )}
                </div>
                {canWrite && (
                  <div className="flex items-center gap-2 pt-2 border-t border-border/50">
                    <Button
                      size="sm"
                      variant="primary"
                      icon={CheckCircle2}
                      onClick={() => handleAppearanceAction(selectedItem.id, 'approve')}
                      disabled={!!busyAction}
                      className="flex-1"
                    >
                      Approve Reference
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      icon={RefreshCw}
                      onClick={() => handleAppearanceAction(selectedItem.id, 'regenerate')}
                      disabled={!!busyAction}
                      className="flex-1"
                    >
                      Regenerate Sheet
                    </Button>
                  </div>
                )}
              </div>
            )}

            {selectedItem?.kind === 'video_run' && (
              <div className="space-y-4">
                {selectedItem.data.run.output_video_signed_url && (
                  <div className="aspect-video rounded-xl overflow-hidden bg-black border border-border">
                    <video
                      key={selectedItem.data.run.output_video_signed_url}
                      controls
                      preload="metadata"
                      src={selectedItem.data.run.output_video_signed_url}
                      className="w-full h-full"
                    />
                  </div>
                )}
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="font-bold text-foreground">
                    {selectedItem.data.run.shot_id} (Attempt #{selectedItem.data.run.attempt})
                  </span>
                  <span className="text-muted-foreground">
                    {selectedItem.data.run.model} · seed {selectedItem.data.run.seed}
                  </span>
                </div>

                {/* Conditioning Frames & Reference Sheets */}
                <div className="space-y-2">
                  <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground block">
                    Conditioning Start / Reference / End Frames
                  </span>
                  <div className="grid grid-cols-3 gap-2">
                    {selectedItem.data.startAsset?.signed_url && (
                      <div className="rounded-lg overflow-hidden border border-amber-500/40 bg-black/50">
                        <img
                          src={selectedItem.data.startAsset.signed_url}
                          alt="Start frame"
                          className="w-full aspect-video object-cover"
                        />
                        <p className="px-1.5 py-0.5 text-[9px] font-mono text-amber-300 truncate">
                          START FRAME
                        </p>
                      </div>
                    )}
                    {(selectedItem.data.refAssets || []).map((ra: any) => (
                      <div
                        key={ra.id}
                        className="rounded-lg overflow-hidden border border-border/60 bg-black/50"
                      >
                        {ra.signed_url && (
                          <img
                            src={ra.signed_url}
                            alt={ra.id}
                            className="w-full aspect-video object-cover"
                          />
                        )}
                        <p className="px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground truncate">
                          {ra.kind}
                        </p>
                      </div>
                    ))}
                    {selectedItem.data.endAsset?.signed_url && (
                      <div className="rounded-lg overflow-hidden border border-emerald-500/40 bg-black/50">
                        <img
                          src={selectedItem.data.endAsset.signed_url}
                          alt="End frame"
                          className="w-full aspect-video object-cover"
                        />
                        <p className="px-1.5 py-0.5 text-[9px] font-mono text-emerald-300 truncate">
                          END FRAME
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {selectedItem.data.run.qa_scores && (
                  <div className="grid grid-cols-2 gap-2 text-[11px] font-mono bg-muted/40 p-3 rounded-lg border border-border/60">
                    <span>
                      Wardrobe:{' '}
                      {(
                        (selectedItem.data.run.qa_scores.wardrobe_match > 1
                          ? selectedItem.data.run.qa_scores.wardrobe_match * 10
                          : selectedItem.data.run.qa_scores.wardrobe_match * 100) || 0
                      ).toFixed(0)}
                      %
                    </span>
                    <span>
                      Setting:{' '}
                      {(
                        (selectedItem.data.run.qa_scores.setting_match > 1
                          ? selectedItem.data.run.qa_scores.setting_match * 10
                          : selectedItem.data.run.qa_scores.setting_match * 100) || 0
                      ).toFixed(0)}
                      %
                    </span>
                    <span>
                      Action:{' '}
                      {(
                        (selectedItem.data.run.qa_scores.action_achieved > 1
                          ? selectedItem.data.run.qa_scores.action_achieved * 10
                          : selectedItem.data.run.qa_scores.action_achieved * 100) || 0
                      ).toFixed(0)}
                      %
                    </span>
                    <span>
                      WER: {(selectedItem.data.run.qa_scores.dialogue_wer * 100).toFixed(1)}%
                    </span>
                  </div>
                )}

                <div className="space-y-1">
                  <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
                    Compiled Shot Prompt
                  </span>
                  <pre className="p-3 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-56 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
                    {selectedItem.data.run.compiled_prompt}
                  </pre>
                </div>
              </div>
            )}

            {selectedItem?.kind === 'shot' && (
              <div className="space-y-4 text-xs">
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark font-mono font-bold">
                    {selectedItem.data.shot.id} · Scene {selectedItem.data.shot.scene_id}
                  </span>
                  <Button
                    size="xs"
                    variant="outline"
                    icon={busyAction === `compile_${selectedItem.id}` ? Loader2 : Terminal}
                    onClick={() => handleCompilePreview(selectedItem.id)}
                    disabled={!!busyAction}
                  >
                    Compile Prompt (S7)
                  </Button>
                </div>

                <div className="p-3 rounded-lg bg-muted/40 border border-border/60 space-y-1 font-mono text-[11px]">
                  <div>
                    Camera: {selectedItem.data.shot.camera?.shot_size} ·{' '}
                    {selectedItem.data.shot.camera?.angle} ·{' '}
                    {selectedItem.data.shot.camera?.movement} ·{' '}
                    {selectedItem.data.shot.camera?.lens_mm}mm
                  </div>
                  <div>Duration: {selectedItem.data.shot.duration_s}s</div>
                </div>

                <div className="space-y-1.5">
                  <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
                    Cast Appearances
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {(selectedItem.data.shot.cast || []).map((c: any) => (
                      <span
                        key={c.entity_id}
                        className="px-2 py-1 rounded bg-card border border-border text-[10px] font-mono"
                      >
                        {c.entity_id} [{c.position}] → {c.appearance_id}
                      </span>
                    ))}
                  </div>
                </div>

                {compiledPreviews[selectedItem.id] && (
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-mono font-bold uppercase text-emerald-400">
                      Compiled Jinja2 Prompt (SHA-256:{' '}
                      {compiledPreviews[selectedItem.id].package_hash.slice(0, 12)})
                    </span>
                    <pre className="p-3 rounded-lg bg-black/80 text-emerald-300 text-[10px] font-mono max-h-60 overflow-y-auto whitespace-pre-wrap border border-emerald-500/20">
                      {compiledPreviews[selectedItem.id].compiled_prompt}
                    </pre>
                  </div>
                )}
              </div>
            )}

            {selectedItem?.kind === 'entity' && (
              <div className="space-y-4 text-xs">
                <div>
                  <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
                    {selectedItem.data.entity_type} · {selectedItem.data.id}
                  </span>
                  <h5 className="text-base font-bold text-foreground mt-1">
                    {selectedItem.data.canonical_name}
                  </h5>
                  {selectedItem.data.aliases?.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Aliases: {selectedItem.data.aliases.join(', ')}
                    </p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <span className="text-[10px] font-mono font-bold uppercase text-muted-foreground">
                    Canonical Attributes & Provenance
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(selectedItem.data.attributes || {}).map(
                      ([k, v]: [string, any]) => (
                        <span
                          key={k}
                          className={cn(
                            'px-2 py-1 rounded text-[10px] font-mono border',
                            v.provenance === 'from_text'
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                              : 'bg-amber-500/10 text-amber-400 border-amber-500/25',
                          )}
                        >
                          {k}: {v.value} ({v.provenance})
                        </span>
                      ),
                    )}
                  </div>
                </div>
              </div>
            )}

            {selectedItem?.kind === 'scene' && (
              <div className="space-y-3 text-xs">
                <span className="px-2 py-0.5 rounded bg-accent/15 text-accent-dark text-[10px] font-mono font-bold uppercase">
                  Scene {selectedItem.data.scene.index} · {selectedItem.data.scene.id}
                </span>
                <h5 className="text-sm font-bold text-foreground">
                  {selectedItem.data.scene.heading}
                </h5>
                <p className="text-muted-foreground leading-relaxed">
                  {selectedItem.data.scene.summary}
                </p>
              </div>
            )}

            {/* 10-STAGE PIPELINE TELEMETRY & INDIVIDUAL STAGE TRIGGERS */}
            <div className="pt-3 border-t border-border/60 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <Cpu size={12} className="text-accent-dark" /> 10-Stage Execution Telemetry
                </span>
                <span className="text-[10px] font-mono text-muted-foreground">
                  Click Re-Run to execute any stage
                </span>
              </div>

              <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
                {PIPELINE_SUB_STAGES.map((st) => {
                  const sr = latestStageRunByStage[st.id]
                  const isDone = completedStages.has(st.id)
                  const isFailed = sr?.status === 'failed' || !!sr?.error
                  const gateObj = st.gate ? gatesById[st.gate] : null
                  return (
                    <div
                      key={st.id}
                      onClick={() => {
                        setExpandAllSteps(false)
                        setActiveStep(st.stepGroup)
                      }}
                      className={cn(
                        'cursor-pointer p-2.5 rounded-xl border transition-all flex items-center justify-between gap-2',
                        isFailed
                          ? 'bg-red-500/15 border-red-500/50'
                          : activeStep === st.stepGroup
                            ? 'bg-accent/10 border-accent/40'
                            : isDone
                              ? 'bg-muted/30 border-border/60 hover:border-emerald-500/40'
                              : 'bg-muted/15 border-border/40',
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {isFailed ? (
                            <AlertTriangle size={12} className="text-red-400 shrink-0" />
                          ) : isDone ? (
                            <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />
                          ) : (
                            <Clock size={12} className="text-muted-foreground shrink-0" />
                          )}
                          <span className="text-[11px] font-mono font-bold text-foreground">
                            {st.short} · {st.label}
                          </span>
                          {st.gate && (
                            <span
                              className={cn(
                                'px-1.5 py-0.2 rounded text-[9px] font-mono font-bold',
                                gateObj?.decision === 'approved'
                                  ? 'bg-emerald-500/20 text-emerald-400'
                                  : 'bg-amber-500/20 text-amber-400',
                              )}
                            >
                              {st.gate}
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] font-mono text-muted-foreground truncate mt-0.5">
                          {st.role}
                          {sr?.duration_s ? ` · ${sr.duration_s.toFixed(1)}s` : ''}
                          {sr?.images_generated ? ` · ${sr.images_generated} imgs` : ''}
                          {sr?.videos_generated ? ` · ${sr.videos_generated} clips` : ''}
                        </div>
                      </div>

                      {canWrite && (
                        <div onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="xs"
                            variant="ghost"
                            icon={busyAction === st.id ? Loader2 : RefreshCw}
                            onClick={() => handleRunStage(st.id)}
                            disabled={!!busyAction || isRunningPipeline}
                            title={`Run ${st.id}`}
                          >
                            Run
                          </Button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
