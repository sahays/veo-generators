import { Box } from 'lucide-react'
import type { StoryGraphData } from '@/types/project'
import type { MacroStepCardDef } from '../storyGraphStudioTypes'

/** Stage id the backend records previz runs under in `stage_runs` (not part of PIPELINE_SUB_STAGES). */
export const PREVIZ_STEP_STAGE = 'S8_PREVIZ'

/**
 * Macro-step card for the optional Blender previz step. `stages` is empty on purpose: previz
 * runs outside the linear pipeline, so it never gates progress or becomes the "first open" step.
 * Its badge comes from the latest `primaryStage` (S8_PREVIZ) run; see `deriveStepState`.
 * Metrics only use the lean snapshot; the previz board itself is fetched when the step opens.
 */
export function buildPrevizStepCard(storyGraph: StoryGraphData | undefined): MacroStepCardDef {
  const shots = storyGraph?.shots || []
  const scenes = storyGraph?.scenes || []
  return {
    id: 'previz', stepNum: 'PREVIZ', stages: [], primaryStage: PREVIZ_STEP_STAGE, title: 'Blender Previz', subtitle: 'GREYBOX 3D BLOCKING · E1 OMNI / E2 KEYFRAME RESTYLE', icon: Box,
    metricPrimary: `${shots.length} Shots · ${scenes.length} Scenes`, metricSecondary: 'Optional · Greybox + AI restyle',
    summaryText: 'Stages each location as a Blender set, renders a greybox previz of every shot, and optionally restyles it via Omni (E1) or restyled keyframes animated by Veo (E2).',
    inputsSummary: 'Directed Shots · Camera Blocking · Location Layouts', outputsSummary: 'Greybox Previz Clips + Optional E1 / E2 Restyled Renders',
  }
}
