import type { ReactNode } from 'react'
import type { Project, StoryGraphData } from '@/types/project'
import type {
  ActiveStepId,
  DesignFilter,
  SelectedInspectorItem,
  deriveEntityAndAssetMaps,
  useStoryGraphStudioActions,
} from '../storyGraphStudioTypes'
import { StepWorldBibleSection, StepScreenplaySection, StepVisualReferenceSheetsSection } from '../StudioStepsWorldToImages'
import { StepShotBreakdownSection, StepValidatorCompilerSection, StepVideoRendersSection } from '../StudioStepsShotsToVideos'
import { AssemblyReadinessPanel } from '../AssemblyReadinessPanel'

export interface StepSectionContext {
  productionId: string
  storyGraph?: StoryGraphData
  canWrite: boolean
  pipelineStatus?: string
  finalVideoUrl?: string
  renderQuality?: 'draft' | 'final'
  videoResolution?: '360p' | '720p' | '1080p'
  onGraphUpdated: (snapshot: Project) => void
  actions: ReturnType<typeof useStoryGraphStudioActions>
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>
  designFilter: DesignFilter
  setDesignFilter: (f: DesignFilter) => void
  selectedItem: SelectedInspectorItem | null
  setSelectedItem: (item: SelectedInspectorItem | null) => void
}

function runProps(c: StepSectionContext) {
  return {
    canWrite: c.canWrite,
    busyAction: c.actions.busyAction,
    isRunningPipeline: c.actions.isRunningPipeline,
    onRunStage: c.actions.handleRunStage,
  }
}

function selectProps(c: StepSectionContext) {
  return { selectedItem: c.selectedItem, onSelectItem: c.setSelectedItem }
}

const renderWorld = (c: StepSectionContext) => (
  <StepWorldBibleSection
    {...runProps(c)} {...selectProps(c)}
    styleGuide={c.storyGraph?.style_guide} characters={c.entityMaps.characters} locations={c.entityMaps.locations} objects={c.entityMaps.objects}
    appearances={c.entityMaps.appearances} events={c.storyGraph?.events || []} stateFacts={c.storyGraph?.state_facts || []}
  />
)

const renderScript = (c: StepSectionContext) => (
  <StepScreenplaySection
    {...runProps(c)} {...selectProps(c)}
    scenes={c.storyGraph?.scenes || []} events={c.storyGraph?.events || []} dialogueLines={c.storyGraph?.dialogue_lines || []} entityMap={c.entityMaps.entityMap}
  />
)

const renderImages = (c: StepSectionContext) => (
  <StepVisualReferenceSheetsSection
    {...runProps(c)} {...selectProps(c)}
    appearancesCount={c.entityMaps.appearances.length} filteredAppearances={c.entityMaps.filteredAppearances} entityMap={c.entityMaps.entityMap}
    designFilter={c.designFilter} onDesignFilterChange={c.setDesignFilter} onAppearanceAction={c.actions.handleAppearanceAction}
  />
)

const renderShots = (c: StepSectionContext) => (
  <StepShotBreakdownSection
    {...runProps(c)} {...selectProps(c)}
    shots={c.storyGraph?.shots || []} dialogueLines={c.storyGraph?.dialogue_lines || []} musicCues={c.storyGraph?.music_cues || []} scenes={c.storyGraph?.scenes || []}
  />
)

const renderPrompts = (c: StepSectionContext) => (
  <StepValidatorCompilerSection
    {...runProps(c)}
    validationIssues={c.storyGraph?.validation_issues || []} changeRequests={c.storyGraph?.change_requests || []} auditLog={c.storyGraph?.audit_log || []}
  />
)

const renderVideos = (c: StepSectionContext) => (
  <StepVideoRendersSection
    {...runProps(c)} {...selectProps(c)}
    shotsCount={(c.storyGraph?.shots || []).length} generationRunsCount={c.entityMaps.generationRuns.length} activeGenerationRuns={c.entityMaps.activeGenerationRuns}
    assetsById={c.entityMaps.assetsById} finalVideoUrl={c.finalVideoUrl} renderQuality={c.renderQuality} videoResolution={c.videoResolution}
    assemblyPanel={
      <AssemblyReadinessPanel
        productionId={c.productionId} pipelineStatus={c.pipelineStatus} activeGenerationRuns={c.entityMaps.activeGenerationRuns}
        canWrite={c.canWrite} isBusy={c.actions.busyAction !== null || c.actions.isRunningPipeline} onGraphUpdated={c.onGraphUpdated}
        onStitchFinalCut={() => void c.actions.handleRetryStage('S10_ASSEMBLE')}
      />
    }
  />
)

const STEP_RENDERERS: Record<ActiveStepId, (c: StepSectionContext) => ReactNode> = {
  s1_world: renderWorld,
  s2_scripts: renderScript,
  s3_images: renderImages,
  s4_s5_shots: renderShots,
  s6_s7_compile: renderPrompts,
  s8_s10_videos: renderVideos,
}

/** Render the full workspace for one macro step (only called for expanded steps). */
export function renderStepSection(id: ActiveStepId, ctx: StepSectionContext): ReactNode {
  return STEP_RENDERERS[id](ctx)
}
