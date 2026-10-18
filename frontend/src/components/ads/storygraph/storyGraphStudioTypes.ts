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

export type StudioLayoutOrientation = 'left-right' | 'top-bottom'

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
  inputsSummary: string
  kitchenSummary: string
  outputsSummary: string
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
  { id: 'S1_EXTRACT', short: 'A1', label: 'Story Architect', role: 'STORY_ARCHITECT + SUPERVISOR', stepGroup: 's1_world', gate: 'G1' },
  { id: 'S2_SCREENPLAY', short: 'A2', label: 'Screenplay Writer', role: 'ALGORITHMIC SCREENWRITER', stepGroup: 's2_scripts' },
  { id: 'S3_DESIGN', short: 'A3', label: 'Design Studio', role: 'CHAR / LOC / OBJ DESIGNERS', stepGroup: 's3_images', gate: 'G2' },
  { id: 'S4_SHOTS', short: 'A4', label: 'Film Director', role: 'DIRECTOR AGENT', stepGroup: 's4_s5_shots' },
  { id: 'S5_MUSIC', short: 'A4b', label: 'Music & Foley Director', role: 'MUSIC + FOLEY + SFX', stepGroup: 's4_s5_shots', gate: 'G3' },
  { id: 'S6_VALIDATE', short: 'A5', label: 'O(V+E) Graph Verifier', role: 'STAGE QA + V1–V13', stepGroup: 's6_s7_compile' },
  { id: 'S7_COMPILE', short: 'A5b', label: 'Prompt Compiler', role: 'BUDGETER + JINJA2', stepGroup: 's6_s7_compile' },
  { id: 'S8_RENDER', short: 'A6', label: 'Cinematographer (Veo)', role: 'GEMINI OMNI / VEO', stepGroup: 's8_s10_videos' },
  { id: 'S9_QA', short: 'A6b', label: 'Clip VLM Critic', role: 'CRITIC VLM', stepGroup: 's8_s10_videos' },
  { id: 'S10_ASSEMBLE', short: 'A6c', label: 'Master Editor', role: 'FFMPEG ASSEMBLER', stepGroup: 's8_s10_videos' },
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

function buildWorldToDesignCards(
  storyGraph: StoryGraphData | undefined,
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>,
): MacroStepCardDef[] {
  const scenes = storyGraph?.scenes || [], events = storyGraph?.events || [], dialogueLines = storyGraph?.dialogue_lines || []
  const totalInteractionSteps = scenes.reduce((acc, sc) => acc + (sc.interaction_steps?.length || 0), 0)
  const { characters, locations, objects, appearances, approvedAppearancesCount, auxiliaryAssets } = entityMaps
  return [
    {
      id: 's1_world', stepNum: 'AGENT 01', stages: ['S1_EXTRACT'], primaryStage: 'S1_EXTRACT', title: 'Story Architect & Supervisor', subtitle: 'WORLD BIBLE · ENTITIES · STYLE LOCK', icon: User, gate: 'G1',
      metricPrimary: `${characters.length + locations.length + objects.length} Canonical Entities`, metricSecondary: `${characters.length} Chars · ${locations.length} Locs · ${objects.length} Props · ${events.length} Events`,
      summaryText: storyGraph?.style_guide?.visual_medium || 'Extracts canonical characters, locations, props, and locks 9.1–9.3 consistency rules.', inputsSummary: 'Story Brief · Visual Style & Color Palette · Directorial Preset', kitchenSummary: `Entity Provenance Graph · ${events.length} Causal Events · S1 Stage QA Verification`, outputsSummary: `${characters.length} Characters, ${locations.length} Locations, ${objects.length} Props & StyleGuide`,
    },
    {
      id: 's2_scripts', stepNum: 'AGENT 02', stages: ['S2_SCREENPLAY'], primaryStage: 'S2_SCREENPLAY', title: 'Screenplay Writer', subtitle: 'ALGORITHMIC 1-ACTION-AT-A-TIME SCRIPT', icon: FileText,
      metricPrimary: `${scenes.length} Scenes · ${totalInteractionSteps || events.length} Steps`, metricSecondary: `${dialogueLines.length} Dialogue Lines · 1 Action/Step`,
      summaryText: scenes[0]?.summary || 'Writes ordered, step-by-step character & environment interaction algorithms.', inputsSummary: 'Canonical Entities · Ordered StoryEvents · Auto-Bound Screenplay Style', kitchenSummary: `${totalInteractionSteps} Atomic InteractionSteps (Actor → Verb → Target → Env/Sound)`, outputsSummary: `${scenes.length} Structured Scenes & ${dialogueLines.length} Lip-Synced Dialogue Lines`,
    },
    {
      id: 's3_images', stepNum: 'AGENT 03', stages: ['S3_DESIGN'], primaryStage: 'S3_DESIGN', title: 'Visual Design Studio', subtitle: '9.2 CHARACTER & 9.3 SCENE ANCHORS', icon: Sparkles, gate: 'G2',
      metricPrimary: `${appearances.length} Reference Sheets`, metricSecondary: `${approvedAppearancesCount}/${appearances.length} Approved · ${auxiliaryAssets.length} Composites`,
      summaryText: 'Generates character identity sheets, location plates, and hero props verified by VLM Critic.', inputsSummary: 'Entity Visual Attributes · StyleGuide Medium · Color Palette Swatches', kitchenSummary: `Multi-Angle Turnarounds · VLM Identity Checks · ${auxiliaryAssets.length} Composite Plates`, outputsSummary: `${approvedAppearancesCount} Approved Reference Anchors for Downstream Conditioning`,
    },
  ]
}

function buildDirectionToVideoCards(
  storyGraph: StoryGraphData | undefined,
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>,
  finalVideoUrl?: string,
): MacroStepCardDef[] {
  const shots = storyGraph?.shots || [], musicCues = storyGraph?.music_cues || [], validationIssues = storyGraph?.validation_issues || []
  const auditLog = storyGraph?.audit_log || [], qaReports = storyGraph?.stage_qa_reports || []
  const { activeGenerationRuns } = entityMaps
  return [
    {
      id: 's4_s5_shots', stepNum: 'AGENT 04', stages: ['S4_SHOTS', 'S5_MUSIC'], primaryStage: 'S4_SHOTS', title: 'Film Director & Music Director', subtitle: 'CAMERA BLOCKING · FOLEY · AMBIENCE · SFX', icon: Film, gate: 'G3',
      metricPrimary: `${shots.length} Directed Shots`, metricSecondary: `${musicCues.length} Cues · Foley, Wind & Action SFX`,
      summaryText: 'Translates algorithmic steps into camera lenses, 9.1 motion vectors, footsteps, wind, and action SFX.', inputsSummary: 'Algorithmic InteractionSteps · Directorial Preset · Auto-Bound Soundscape', kitchenSummary: '180° Axis & Motion Vectors · Footsteps/Wind Foley · Action-Focus SFX', outputsSummary: `${shots.length} Camera-Blocked Shots & ${musicCues.length} Multi-Layer Audio Cues`,
    },
    {
      id: 's6_s7_compile', stepNum: 'AGENT 05', stages: ['S6_VALIDATE', 'S7_COMPILE'], primaryStage: 'S7_COMPILE', title: 'Graph Verifier & Prompt Compiler', subtitle: 'O(V+E) QA CRITIC · V1–V13 · JINJA2', icon: ShieldCheck,
      metricPrimary: validationIssues.length === 0 ? 'O(V+E) Graph Verified' : `${validationIssues.length} Graph Alerts`, metricSecondary: `${qaReports.length} Stage QA Reports · ${auditLog.length} Audits`,
      summaryText: 'Runs single-pass O(V+E) graph verification, shift-left QA remediation, and deterministic Jinja2 compilation.', inputsSummary: 'Complete StoryGraph (Entities, Scenes, Appearances, Shots, Audio Cues)', kitchenSummary: 'O(V+E) Missing-Asset & 9.1–9.3 Consistency Sweep · Reference Image Budgeter', outputsSummary: 'Verified ShotPromptPackages with SHA-256 Hashes & Reference Assets',
    },
    {
      id: 's8_s10_videos', stepNum: 'AGENT 06', stages: ['S8_RENDER', 'S9_QA', 'S10_ASSEMBLE'], primaryStage: 'S8_RENDER', title: 'Cinematographer & Master Editor', subtitle: 'VEO RENDER · CLIP VLM QA · FFMPEG CUT', icon: Play,
      metricPrimary: `${activeGenerationRuns.length}/${shots.length} Video Clips`, metricSecondary: finalVideoUrl ? 'Master Final Cut Stitched' : 'Awaiting Final Cut Render',
      summaryText: 'Renders reference-conditioned Veo clips, extracts continuity frames, scores VLM QA, and stitches the master cut.', inputsSummary: 'Compiled ShotPromptPackages · Reference Sheets · Continuity Start Frames', kitchenSummary: 'Extracted Last Frames · VLM Clip QA (Wardrobe/Setting/Action/WER) · FFmpeg Normalize', outputsSummary: finalVideoUrl ? 'Stitched Master MP4 + Verified Shot Clips' : `${activeGenerationRuns.length} Rendered Shot Clips`,
    },
  ]
}

function buildMacroStepCardList(
  storyGraph: StoryGraphData | undefined,
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>,
  finalVideoUrl?: string,
): MacroStepCardDef[] {
  return [
    ...buildWorldToDesignCards(storyGraph, entityMaps),
    ...buildDirectionToVideoCards(storyGraph, entityMaps, finalVideoUrl),
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
