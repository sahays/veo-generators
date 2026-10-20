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
import { PIPELINE_SUB_STAGES } from './cascade/pipelineStages'
import { runStageWithRecovery, type StudioProjectsApi } from './cascade/stageRunner'
import { useStageCascade } from './cascade/useStageCascade'

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
  metricPrimary: string
  metricSecondary: string
  summaryText: string
  inputsSummary: string
  outputsSummary: string
  [key: string]: unknown
}

export { PIPELINE_SUB_STAGES }

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
  const pendingGate = blockedGate || null
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
      id: 's1_world', stepNum: 'AGENT 01', stages: ['S1_EXTRACT'], primaryStage: 'S1_EXTRACT', title: 'Story Architect & Supervisor', subtitle: 'WORLD BIBLE · ENTITIES · STYLE LOCK', icon: User,
      metricPrimary: `${characters.length + locations.length + objects.length} Canonical Entities`, metricSecondary: `${characters.length} Chars · ${locations.length} Locs · ${objects.length} Props · ${events.length} Events`,
      summaryText: storyGraph?.style_guide?.visual_medium || 'Extracts canonical characters, locations, props, and locks 9.1–9.3 consistency rules.', inputsSummary: 'Story Brief · Visual Style & Color Palette · Directorial Preset', outputsSummary: `${characters.length} Characters, ${locations.length} Locations, ${objects.length} Props & StyleGuide`,
    },
    {
      id: 's2_scripts', stepNum: 'AGENT 02', stages: ['S2_SCREENPLAY'], primaryStage: 'S2_SCREENPLAY', title: 'Screenplay Writer', subtitle: 'ALGORITHMIC 1-ACTION-AT-A-TIME SCRIPT', icon: FileText,
      metricPrimary: `${scenes.length} Scenes · ${totalInteractionSteps || events.length} Steps`, metricSecondary: `${dialogueLines.length} Dialogue Lines · 1 Action/Step`,
      summaryText: scenes[0]?.summary || 'Writes ordered, step-by-step character & environment interaction algorithms.', inputsSummary: 'Canonical Entities · Ordered StoryEvents · Auto-Bound Screenplay Style', outputsSummary: `${scenes.length} Structured Scenes & ${dialogueLines.length} Lip-Synced Dialogue Lines`,
    },
    {
      id: 's3_images', stepNum: 'AGENT 03', stages: ['S3_DESIGN'], primaryStage: 'S3_DESIGN', title: 'Visual Design Studio', subtitle: '9.2 CHARACTER & 9.3 SCENE ANCHORS', icon: Sparkles,
      metricPrimary: `${appearances.length} Reference Sheets`, metricSecondary: `${approvedAppearancesCount}/${appearances.length} Approved · ${auxiliaryAssets.length} Composites`,
      summaryText: 'Generates character identity sheets, location plates, and hero props verified by VLM Critic.', inputsSummary: 'Entity Visual Attributes · StyleGuide Medium · Color Palette Swatches', outputsSummary: `${approvedAppearancesCount} Approved Reference Anchors for Downstream Conditioning`,
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
      id: 's4_s5_shots', stepNum: 'AGENT 04', stages: ['S4_SHOTS', 'S5_MUSIC'], primaryStage: 'S4_SHOTS', title: 'Film Director & Music Director', subtitle: 'CAMERA BLOCKING · FOLEY · AMBIENCE · SFX', icon: Film,
      metricPrimary: `${shots.length} Directed Shots`, metricSecondary: `${musicCues.length} Cues · Foley, Wind & Action SFX`,
      summaryText: 'Translates algorithmic steps into camera lenses, 9.1 motion vectors, footsteps, wind, and action SFX.', inputsSummary: 'Algorithmic InteractionSteps · Directorial Preset · Auto-Bound Soundscape', outputsSummary: `${shots.length} Camera-Blocked Shots & ${musicCues.length} Multi-Layer Audio Cues`,
    },
    {
      id: 's6_s7_compile', stepNum: 'AGENT 05', stages: ['S6_VALIDATE', 'S7_COMPILE'], primaryStage: 'S7_COMPILE', title: 'Graph Verifier & Prompt Compiler', subtitle: '3× ITERATIVE REVIEW · V1–V13 · JINJA2', icon: ShieldCheck,
      metricPrimary: validationIssues.length === 0 ? 'O(V+E) Graph Verified' : `${validationIssues.length} Graph Alerts`, metricSecondary: `${qaReports.length} Stage Reviews · ${auditLog.length} Audits`,
      summaryText: 'Reviews work across agents, redoes upstream steps up to 3× if flaws are found, and compiles prompts.', inputsSummary: 'Complete StoryGraph (Entities, Scenes, Appearances, Shots, Audio Cues)', outputsSummary: 'Verified ShotPromptPackages with SHA-256 Hashes & Reference Assets',
    },
    {
      id: 's8_s10_videos', stepNum: 'AGENT 06', stages: ['S8_RENDER', 'S9_QA', 'S10_ASSEMBLE'], primaryStage: 'S8_RENDER', title: 'Cinematographer & Master Editor', subtitle: 'VEO RENDER · PHYSICS VLM QA · FFMPEG CUT', icon: Play,
      metricPrimary: `${activeGenerationRuns.length}/${shots.length} Video Clips`, metricSecondary: finalVideoUrl ? 'Master Final Cut Stitched' : 'Awaiting Final Cut Render',
      summaryText: 'Renders reference-conditioned Veo clips, critically QAs physics & object permanence, and stitches the master cut.', inputsSummary: 'Compiled ShotPromptPackages · Reference Sheets · Continuity Start Frames', outputsSummary: finalVideoUrl ? 'Stitched Master MP4 + Physics-Verified Shot Clips' : `${activeGenerationRuns.length} Rendered Shot Clips`,
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

async function executePipelineForward(
  projectsApi: StudioProjectsApi,
  productionId: string,
  completedStages: Set<string> | undefined,
  onGraphUpdated: (snapshot: Project) => void,
  setBusyAction: (s: string | null) => void,
  setFailedStage: (s: string | null) => void,
  setErrorMsg: (s: string | null) => void,
  setIsRunningPipeline: (b: boolean) => void,
) {
  setIsRunningPipeline(true); setErrorMsg(null); setFailedStage(null)
  const done = new Set(completedStages || [])
  let currentSubId: string | null = null
  try {
    for (const sub of PIPELINE_SUB_STAGES) {
      if (done.has(sub.id)) continue
      currentSubId = sub.id; setBusyAction(sub.id)
      const snap = await runStageWithRecovery(projectsApi, productionId, sub.id, false, onGraphUpdated)
      onGraphUpdated(snap)
      for (const sr of snap.story_graph?.stage_runs || []) if (sr.completed) done.add(sr.stage)
    }
  } catch (err) {
    setFailedStage(currentSubId)
    setErrorMsg(err instanceof Error ? err.message : 'Pipeline execution failed')
  } finally {
    setBusyAction(null); setIsRunningPipeline(false)
  }
}

export function useStoryGraphStudioActions(
  productionId: string,
  onGraphUpdated: (snapshot: Project) => void,
  completedStages?: Set<string>,
) {
  const { projects: projectsApi } = useAdsProjectActions()
  const [isRunningPipeline, setIsRunningPipeline] = useState(false)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [failedStage, setFailedStage] = useState<string | null>(null)
  const [compiledPreviews, setCompiledPreviews] = useState<Record<string, CompiledShotPreview>>({})
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const handleRunForward = () =>
    executePipelineForward(projectsApi, productionId, completedStages, onGraphUpdated, setBusyAction, setFailedStage, setErrorMsg, setIsRunningPipeline)

  const handleRunStage = (stageId: string, quality?: 'draft' | 'final') => {
    setFailedStage(null)
    return runWithBusyKey(stageId, setBusyAction, (msg) => { if (msg) setFailedStage(stageId); setErrorMsg(msg) }, `Stage ${stageId} failed`, () => runStageWithRecovery(projectsApi, productionId, stageId, true, onGraphUpdated, quality), onGraphUpdated)
  }

  const handleAppearanceAction = (appearanceId: string, action: 'approve' | 'regenerate') =>
    runWithBusyKey(`app_${appearanceId}_${action}`, setBusyAction, setErrorMsg, 'Appearance action failed', () =>
      action === 'approve' ? projectsApi.approveAppearance(productionId, appearanceId) : projectsApi.regenerateAppearance(productionId, appearanceId), onGraphUpdated)

  const handleCompilePreview = (shotId: string) =>
    runWithBusyKey(`compile_${shotId}`, setBusyAction, setErrorMsg, 'Shot compilation preview failed', () =>
      projectsApi.compileShot(productionId, shotId), (res) => setCompiledPreviews((prev) => ({ ...prev, [shotId]: res })))

  const cascade = useStageCascade({ projectsApi, productionId, onGraphUpdated, setBusyAction, setFailedStage, setErrorMsg })

  return {
    isRunningPipeline: isRunningPipeline || cascade.isCascading, busyAction, failedStage, compiledPreviews, errorMsg, setErrorMsg,
    handleRunForward, handleRunStage: cascade.requestCascade, handleRetryStage: handleRunStage, handleAppearanceAction, handleCompilePreview, cascade,
  }
}
