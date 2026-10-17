import { useState, useMemo } from 'react'
import { User, FileText, Sparkles, Film, ShieldCheck, Play } from 'lucide-react'
import type {
  Project,
  StoryGraphAppearance,
  StoryGraphAsset,
  StoryGraphData,
  StoryGraphDialogueLine,
  StoryGraphEntity,
  StoryGraphEvent,
  StoryGraphGate,
  StoryGraphGenerationRun,
  StoryGraphMusicCue,
  StoryGraphScene,
  StoryGraphShot,
  StoryGraphStageRun,
} from '@/types/project'
import { useAdsProjectActions } from '../projects/useAdsProjectActions'

export type ActiveStepId =
  | 's1_world'
  | 's2_scripts'
  | 's3_images'
  | 's4_s5_shots'
  | 's6_s7_compile'
  | 's8_s10_videos'

export type DesignFilter = 'all' | 'character' | 'location' | 'object'

export interface CompiledShotPreview {
  package_hash: string
  compiled_prompt: string
}

export type SelectedInspectorItem =
  | { kind: 'stage'; id: string; data: Record<string, unknown> }
  | { kind: 'entity'; id: string; data: StoryGraphEntity }
  | {
      kind: 'scene'
      id: string
      data: {
        scene: StoryGraphScene
        events: StoryGraphEvent[]
        dialogues: StoryGraphDialogueLine[]
        loc?: StoryGraphEntity
      }
    }
  | {
      kind: 'appearance'
      id: string
      data: {
        appearance: StoryGraphAppearance
        entity?: StoryGraphEntity
        asset?: StoryGraphAsset
      }
    }
  | {
      kind: 'shot'
      id: string
      data: {
        shot: StoryGraphShot
        dialogues: StoryGraphDialogueLine[]
        cue?: StoryGraphMusicCue
      }
    }
  | {
      kind: 'video_run'
      id: string
      data: {
        run: StoryGraphGenerationRun
        startAsset?: StoryGraphAsset | null
        refAssets: StoryGraphAsset[]
        endAsset?: StoryGraphAsset | null
      }
    }

export interface MacroStepCardDef {
  id: ActiveStepId
  stepNum: string
  stages: string[]
  primaryStage: string
  title: string
  subtitle: string
  icon: typeof User
  gate?: 'G1' | 'G2' | 'G3'
  metricPrimary: string
  metricSecondary: string
  summaryText: string
  [key: string]: unknown
}

export const PIPELINE_SUB_STAGES: Array<{
  id: string
  short: string
  label: string
  role: string
  stepGroup: ActiveStepId
  gate?: 'G1' | 'G2' | 'G3'
}> = [
  { id: 'S1_EXTRACT', short: 'S1', label: 'World & Entities', role: 'STORY_ARCHITECT + SUPERVISOR', stepGroup: 's1_world', gate: 'G1' },
  { id: 'S2_SCREENPLAY', short: 'S2', label: 'Scene Scripts', role: 'SCREENWRITER', stepGroup: 's2_scripts' },
  { id: 'S3_DESIGN', short: 'S3', label: 'Reference Images', role: 'CHAR / LOC / OBJ DESIGNERS', stepGroup: 's3_images', gate: 'G2' },
  { id: 'S4_SHOTS', short: 'S4', label: 'Shot Breakdown', role: 'DIRECTOR', stepGroup: 's4_s5_shots' },
  { id: 'S5_MUSIC', short: 'S5', label: 'Music & SFX', role: 'MUSIC_DIRECTOR', stepGroup: 's4_s5_shots', gate: 'G3' },
  { id: 'S6_VALIDATE', short: 'S6', label: 'Validator V1–V13', role: 'DETERMINISTIC', stepGroup: 's6_s7_compile' },
  { id: 'S7_COMPILE', short: 'S7', label: 'Prompt Compiler', role: 'BUDGETER + JINJA2', stepGroup: 's6_s7_compile' },
  { id: 'S8_RENDER', short: 'S8', label: 'Video Render', role: 'GEMINI OMNI / VEO', stepGroup: 's8_s10_videos' },
  { id: 'S9_QA', short: 'S9', label: 'Clip VLM QA', role: 'CRITIC VLM', stepGroup: 's8_s10_videos' },
  { id: 'S10_ASSEMBLE', short: 'S10', label: 'Final Cut', role: 'FFMPEG ASSEMBLER', stepGroup: 's8_s10_videos' },
]

export function deriveStageAndGateMaps(
  storyGraph: StoryGraphData | undefined,
  blockedGate?: string | null,
  pipelineStatus?: string,
  pipelineError?: string | null,
  errorMsg?: string | null,
) {
  const stageRuns = storyGraph?.stage_runs || []
  const completedStages = new Set(stageRuns.filter((sr) => sr.completed).map((sr) => sr.stage))
  const latestStageRunByStage: Record<string, StoryGraphStageRun> = {}
  for (const sr of stageRuns) latestStageRunByStage[sr.stage] = sr
  const failedStageRuns = Object.values(latestStageRunByStage).filter(
    (sr) => sr.status === 'failed' || sr.error,
  )
  const gatesById: Record<string, StoryGraphGate> = {}
  for (const g of storyGraph?.gates || []) gatesById[g.gate_id] = g
  const pendingGate =
    blockedGate || (['G1', 'G2', 'G3'].find((gid) => gatesById[gid]?.decision === 'pending') ?? null)
  const activeError =
    errorMsg ||
    (pipelineStatus === 'failed' ? pipelineError || 'Pipeline execution failed' : null) ||
    (failedStageRuns.length > 0
      ? `Stage ${failedStageRuns[failedStageRuns.length - 1].stage} failed: ${failedStageRuns[failedStageRuns.length - 1].error}`
      : null)

  return { completedStages, latestStageRunByStage, gatesById, pendingGate, activeError }
}

export function deriveEntityAndAssetMaps(storyGraph: StoryGraphData | undefined, designFilter: DesignFilter) {
  const characters = storyGraph?.entities?.characters || []
  const locations = storyGraph?.entities?.locations || []
  const objects = storyGraph?.entities?.objects || []
  const entityMap = Object.fromEntries((storyGraph?.entities?.all || []).map((e) => [e.id, e]))
  const appearances = (storyGraph?.appearances || []).filter((a) => a.status !== 'superseded')
  const approvedAppearancesCount = appearances.filter((a) => a.status === 'approved').length
  const filteredAppearances = appearances.filter((a) => designFilter === 'all' || entityMap[a.entity_id]?.entity_type === designFilter)
  const allAssets = storyGraph?.assets || []
  const assetsById = Object.fromEntries(allAssets.map((a) => [a.id, a]))
  const auxiliaryAssets = allAssets.filter((a) => a.kind === 'composite_sheet' || a.kind === 'first_frame')
  const generationRuns = storyGraph?.generation_runs || []
  const latestRunByShotId: Record<string, StoryGraphGenerationRun> = {}
  for (const r of generationRuns) {
    if (!latestRunByShotId[r.shot_id] || r.attempt >= latestRunByShotId[r.shot_id].attempt) latestRunByShotId[r.shot_id] = r
  }
  return {
    characters, locations, objects, entityMap, appearances, approvedAppearancesCount,
    filteredAppearances, assetsById, auxiliaryAssets, generationRuns, activeGenerationRuns: Object.values(latestRunByShotId),
  }
}

function buildMacroStepCardList(
  storyGraph: StoryGraphData | undefined,
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>,
  finalVideoUrl?: string,
): MacroStepCardDef[] {
  const scenes = storyGraph?.scenes || [], shots = storyGraph?.shots || [], events = storyGraph?.events || []
  const dialogueLines = storyGraph?.dialogue_lines || [], musicCues = storyGraph?.music_cues || []
  const validationIssues = storyGraph?.validation_issues || [], auditLog = storyGraph?.audit_log || []
  const { characters, locations, objects, appearances, approvedAppearancesCount, auxiliaryAssets, activeGenerationRuns } = entityMaps
  return [
    { id: 's1_world', stepNum: 'STEP 01', stages: ['S1_EXTRACT'], primaryStage: 'S1_EXTRACT', title: 'World Bible & Entities', subtitle: 'STORY_ARCHITECT + SUPERVISOR', icon: User, gate: 'G1', metricPrimary: `${characters.length + locations.length + objects.length} Canonical Entities`, metricSecondary: `${characters.length} Chars · ${locations.length} Locs · ${objects.length} Props · ${events.length} Events`, summaryText: storyGraph?.style_guide?.visual_medium || 'Canonical characters, locations, hero objects, and state transitions.' },
    { id: 's2_scripts', stepNum: 'STEP 02', stages: ['S2_SCREENPLAY'], primaryStage: 'S2_SCREENPLAY', title: 'Screenplay & Dialogue', subtitle: 'SCREENWRITER AGENT', icon: FileText, metricPrimary: `${scenes.length} Scenes · ${dialogueLines.length} Lines`, metricSecondary: 'Structured scene scripts & character dialogue', summaryText: scenes[0]?.summary || 'Scene-by-scene action summaries and lip-synced character dialogue.' },
    { id: 's3_images', stepNum: 'STEP 03', stages: ['S3_DESIGN'], primaryStage: 'S3_DESIGN', title: 'Visual Reference Sheets', subtitle: 'CHAR / LOC / OBJ DESIGNERS', icon: Sparkles, gate: 'G2', metricPrimary: `${appearances.length} Reference Images`, metricSecondary: `${approvedAppearancesCount}/${appearances.length} Approved · ${auxiliaryAssets.length} Composites`, summaryText: 'Canonical character sheets, location plates, and hero props evaluated by CRITIC VLM.' },
    { id: 's4_s5_shots', stepNum: 'STEP 04', stages: ['S4_SHOTS', 'S5_MUSIC'], primaryStage: 'S4_SHOTS', title: 'Shot Breakdown & Music', subtitle: 'DIRECTOR + MUSIC_DIRECTOR', icon: Film, gate: 'G3', metricPrimary: `${shots.length} Directed Shots`, metricSecondary: `${musicCues.length} Music Cues · Camera & Continuity Locks`, summaryText: 'Timed ActionBeats, lens & framing specs, start-frame continuity links, and audio cues.' },
    { id: 's6_s7_compile', stepNum: 'STEP 05', stages: ['S6_VALIDATE', 'S7_COMPILE'], primaryStage: 'S7_COMPILE', title: 'Validator & Compiler', subtitle: 'VALIDATOR V1–V13 + JINJA2', icon: ShieldCheck, metricPrimary: validationIssues.length === 0 ? 'All V1–V13 Checks Passed' : `${validationIssues.length} Validation Alerts`, metricSecondary: `${auditLog.length} Graph Mutations Audited`, summaryText: 'Deterministic continuity invariants, reference image budgeting, and Jinja2 prompt compilation.' },
    { id: 's8_s10_videos', stepNum: 'STEP 06', stages: ['S8_RENDER', 'S9_QA', 'S10_ASSEMBLE'], primaryStage: 'S8_RENDER', title: 'Video Clips & Final Cut', subtitle: 'GEMINI OMNI / VEO + FFMPEG', icon: Play, metricPrimary: `${activeGenerationRuns.length}/${shots.length} Video Clips`, metricSecondary: finalVideoUrl ? 'Master Final Cut Stitched' : 'Awaiting Final Cut Render', summaryText: 'Reference-conditioned video clips, start/end continuity frames, VLM QA, and stitched master cut.' },
  ]
}

export function useMacroStepCards(
  storyGraph: StoryGraphData | undefined,
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>,
  finalVideoUrl?: string,
): MacroStepCardDef[] {
  return useMemo(() => buildMacroStepCardList(storyGraph, entityMaps, finalVideoUrl), [storyGraph, entityMaps, finalVideoUrl])
}

async function runWithBusyKey<T>(
  key: string,
  setBusy: (k: string | null) => void,
  setErrorMsg: (e: string | null) => void,
  fallbackErr: string,
  task: () => Promise<T>,
  onDone: (res: T) => void,
) {
  setBusy(key)
  setErrorMsg(null)
  try {
    onDone(await task())
  } catch (err) {
    setErrorMsg(err instanceof Error ? err.message : fallbackErr)
  } finally {
    setBusy(null)
  }
}

export function useStoryGraphStudioActions(
  productionId: string,
  onGraphUpdated: (snapshot: Project) => void,
) {
  const { projects: projectsApi } = useAdsProjectActions()
  const [isRunningPipeline, setIsRunningPipeline] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [gateNotes, setGateNotes] = useState<Record<string, string>>({})
  const [compiledPreviews, setCompiledPreviews] = useState<Record<string, CompiledShotPreview>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const handleRunForward = (autoApprove = false) =>
    runWithBusyKey('forward', (k) => setIsRunningPipeline(Boolean(k)), setErrorMsg, 'Pipeline execution failed', () =>
      projectsApi.runStoryGraph(productionId, { auto_approve_gates: autoApprove ? true : undefined }), onGraphUpdated)

  const handleRunStage = (stageId: string) =>
    runWithBusyKey(stageId, setBusyAction, setErrorMsg, `Stage ${stageId} failed`, () =>
      projectsApi.runStage(productionId, stageId), onGraphUpdated)

  const handleGateDecision = (gateId: 'G1' | 'G2' | 'G3', decision: 'approve' | 'reject') =>
    runWithBusyKey(`gate_${gateId}_${decision}`, setBusyAction, setErrorMsg, `Gate ${gateId} ${decision} failed`, () => {
      const note = gateNotes[gateId]
      return decision === 'approve' ? projectsApi.approveGate(productionId, gateId, note || undefined) : projectsApi.rejectGate(productionId, gateId, note || undefined)
    }, (snap) => { setGateNotes((prev) => ({ ...prev, [gateId]: '' })); onGraphUpdated(snap) })

  const handleAppearanceAction = (appearanceId: string, action: 'approve' | 'regenerate') =>
    runWithBusyKey(`app_${appearanceId}_${action}`, setBusyAction, setErrorMsg, 'Appearance action failed', () =>
      action === 'approve' ? projectsApi.approveAppearance(productionId, appearanceId) : projectsApi.regenerateAppearance(productionId, appearanceId), onGraphUpdated)

  const handleCompilePreview = (shotId: string) =>
    runWithBusyKey(`compile_${shotId}`, setBusyAction, setErrorMsg, 'Shot compilation preview failed', () =>
      projectsApi.compileShot(productionId, shotId), (res) => setCompiledPreviews((prev) => ({ ...prev, [shotId]: res })))

  return {
    isRunningPipeline, busyAction, gateNotes, setGateNotes, compiledPreviews, errorMsg, setErrorMsg,
    handleRunForward, handleRunStage, handleGateDecision, handleAppearanceAction, handleCompilePreview,
  }
}
