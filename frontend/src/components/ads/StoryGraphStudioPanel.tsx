import { useState } from 'react'
import { cn } from '@/lib/utils'
import { StoryGraphVisualizer3D } from '@/components/ads/StoryGraphVisualizer3D'
import type { Project, StoryGraphData } from '@/types/project'
import {
  deriveStageAndGateMaps,
  deriveEntityAndAssetMaps,
  useMacroStepCards,
  useStoryGraphStudioActions,
  type ActiveStepId,
  type DesignFilter,
  type SelectedInspectorItem,
  type StudioLayoutOrientation,
} from './storygraph/storyGraphStudioTypes'
import {
  StrictFailureBanner,
  StudioCommandHeader,
  MasterCutQuickBanner,
} from './storygraph/StudioCommandHeader'
import {
  StepWorldBibleSection,
  StepScreenplaySection,
  StepVisualReferenceSheetsSection,
} from './storygraph/StudioStepsWorldToImages'
import {
  StepShotBreakdownSection,
  StepValidatorCompilerSection,
  StepVideoRendersSection,
} from './storygraph/StudioStepsShotsToVideos'
import { StudioRightInspectorPane } from './storygraph/StudioRightInspectorPane'

interface StoryGraphStudioPanelProps {
  productionId: string
  storyGraph?: StoryGraphData
  currentStage?: string
  pipelineStatus?: string
  pipelineError?: string | null
  blockedGate?: string | null
  finalVideoUrl?: string
  canWrite: boolean
  onGraphUpdated: (snapshot: Project) => void
}

interface WorkspaceProps {
  props: StoryGraphStudioPanelProps
  activeStep: ActiveStepId
  setActiveStep: (step: ActiveStepId) => void
  expandAllSteps: boolean
  setExpandAllSteps: React.Dispatch<React.SetStateAction<boolean>>
  layoutOrientation: StudioLayoutOrientation
  setLayoutOrientation: React.Dispatch<React.SetStateAction<StudioLayoutOrientation>>
  panelSizePct: number
  setPanelSizePct: React.Dispatch<React.SetStateAction<number>>
  show3DGraph: boolean
  setShow3DGraph: React.Dispatch<React.SetStateAction<boolean>>
  showMasterCutBanner: boolean
  setShowMasterCutBanner: React.Dispatch<React.SetStateAction<boolean>>
  designFilter: DesignFilter
  setDesignFilter: (f: DesignFilter) => void
  selectedItem: SelectedInspectorItem | null
  setSelectedItem: (item: SelectedInspectorItem | null) => void
  actions: ReturnType<typeof useStoryGraphStudioActions>
  stageMaps: ReturnType<typeof deriveStageAndGateMaps>
  entityMaps: ReturnType<typeof deriveEntityAndAssetMaps>
  macroStepCards: ReturnType<typeof useMacroStepCards>
}

const StudioWorldToImagesColumn = ({
  props, activeStep, expandAllSteps, designFilter, setDesignFilter, selectedItem, setSelectedItem, actions, stageMaps, entityMaps,
}: WorkspaceProps) => (
  <>
    {(expandAllSteps || activeStep === 's1_world') && (
      <StepWorldBibleSection
        canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRunStage={actions.handleRunStage}
        gateG1={stageMaps.gatesById.G1} gateNoteG1={actions.gateNotes.G1 || ''} onGateNoteG1Change={(v) => actions.setGateNotes((p) => ({ ...p, G1: v }))} onGateDecision={actions.handleGateDecision}
        styleGuide={props.storyGraph?.style_guide} characters={entityMaps.characters} locations={entityMaps.locations} objects={entityMaps.objects}
        appearances={entityMaps.appearances} events={props.storyGraph?.events || []} stateFacts={props.storyGraph?.state_facts || []} selectedItem={selectedItem} onSelectItem={setSelectedItem}
      />
    )}
    {(expandAllSteps || activeStep === 's2_scripts') && (
      <StepScreenplaySection
        scenes={props.storyGraph?.scenes || []} events={props.storyGraph?.events || []} dialogueLines={props.storyGraph?.dialogue_lines || []} entityMap={entityMaps.entityMap}
        canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRunStage={actions.handleRunStage} selectedItem={selectedItem} onSelectItem={setSelectedItem}
      />
    )}
    {(expandAllSteps || activeStep === 's3_images') && (
      <StepVisualReferenceSheetsSection
        appearancesCount={entityMaps.appearances.length} filteredAppearances={entityMaps.filteredAppearances} entityMap={entityMaps.entityMap} designFilter={designFilter} onDesignFilterChange={setDesignFilter}
        canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRunStage={actions.handleRunStage}
        gateG2={stageMaps.gatesById.G2} gateNoteG2={actions.gateNotes.G2 || ''} onGateNoteG2Change={(v) => actions.setGateNotes((p) => ({ ...p, G2: v }))} onGateDecision={actions.handleGateDecision}
        onAppearanceAction={actions.handleAppearanceAction} selectedItem={selectedItem} onSelectItem={setSelectedItem}
      />
    )}
  </>
)

const StudioShotsToVideosColumn = ({
  props, activeStep, expandAllSteps, selectedItem, setSelectedItem, actions, stageMaps, entityMaps,
}: WorkspaceProps) => (
  <>
    {(expandAllSteps || activeStep === 's4_s5_shots') && (
      <StepShotBreakdownSection
        shots={props.storyGraph?.shots || []} dialogueLines={props.storyGraph?.dialogue_lines || []} musicCues={props.storyGraph?.music_cues || []}
        canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRunStage={actions.handleRunStage}
        gateG3={stageMaps.gatesById.G3} gateNoteG3={actions.gateNotes.G3 || ''} onGateNoteG3Change={(v) => actions.setGateNotes((p) => ({ ...p, G3: v }))} onGateDecision={actions.handleGateDecision}
        selectedItem={selectedItem} onSelectItem={setSelectedItem}
      />
    )}
    {(expandAllSteps || activeStep === 's6_s7_compile') && (
      <StepValidatorCompilerSection
        validationIssues={props.storyGraph?.validation_issues || []} changeRequests={props.storyGraph?.change_requests || []} auditLog={props.storyGraph?.audit_log || []}
        canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRunStage={actions.handleRunStage}
      />
    )}
    {(expandAllSteps || activeStep === 's8_s10_videos') && (
      <StepVideoRendersSection
        shotsCount={(props.storyGraph?.shots || []).length} generationRunsCount={entityMaps.generationRuns.length} activeGenerationRuns={entityMaps.activeGenerationRuns}
        assetsById={entityMaps.assetsById} finalVideoUrl={props.finalVideoUrl} canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline}
        onRunStage={actions.handleRunStage} selectedItem={selectedItem} onSelectItem={setSelectedItem}
      />
    )}
  </>
)

const StoryGraphStudioWorkspace = (ws: WorkspaceProps) => {
  const { props, activeStep, setActiveStep, expandAllSteps, setExpandAllSteps, layoutOrientation, setLayoutOrientation, panelSizePct, setPanelSizePct, show3DGraph, setShow3DGraph, showMasterCutBanner, setShowMasterCutBanner, selectedItem, setSelectedItem, actions, stageMaps, entityMaps, macroStepCards } = ws
  const activeAgentCard = macroStepCards.find((c) => c.id === activeStep) || macroStepCards[0]
  const isLeftRight = layoutOrientation === 'left-right'
  const mainWidthClass = panelSizePct === 50 ? 'xl:col-span-6' : panelSizePct === 40 ? 'xl:col-span-7' : 'xl:col-span-8'
  const contextWidthClass = panelSizePct === 50 ? 'xl:col-span-6' : panelSizePct === 40 ? 'xl:col-span-5' : 'xl:col-span-4'
  return (
    <div className="space-y-6 w-full max-w-none">
      {stageMaps.activeError && <StrictFailureBanner activeError={stageMaps.activeError} currentStage={props.currentStage} canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} onRetryStage={actions.handleRunStage} onDismiss={() => actions.setErrorMsg(null)} />}
      <StudioCommandHeader completedStages={stageMaps.completedStages} pendingGate={stageMaps.pendingGate} show3DGraph={show3DGraph} onToggle3DGraph={() => setShow3DGraph((v) => !v)} expandAllSteps={expandAllSteps} onToggleExpandAll={() => setExpandAllSteps((v) => !v)} layoutOrientation={layoutOrientation} onToggleLayoutOrientation={() => setLayoutOrientation((prev) => (prev === 'left-right' ? 'top-bottom' : 'left-right'))} canWrite={props.canWrite} isRunningPipeline={actions.isRunningPipeline} busyAction={actions.busyAction} onRunForward={actions.handleRunForward} macroStepCards={macroStepCards} activeStep={activeStep} latestStageRunByStage={stageMaps.latestStageRunByStage} gatesById={stageMaps.gatesById} onSelectCard={(card) => { setExpandAllSteps(false); setActiveStep(card.id); setSelectedItem({ kind: 'stage', id: card.primaryStage, data: card }) }} />
      {show3DGraph && <StoryGraphVisualizer3D storyGraph={props.storyGraph} canWrite={props.canWrite} onApproveAppearance={(appId) => actions.handleAppearanceAction(appId, 'approve')} onRegenerateAppearance={(appId) => actions.handleAppearanceAction(appId, 'regenerate')} />}
      <div className={cn('w-full items-start gap-6', isLeftRight ? 'grid grid-cols-1 xl:grid-cols-12' : 'flex flex-col space-y-6')}>
        <div className={cn('space-y-6 w-full', isLeftRight ? mainWidthClass : '')}>
          {props.finalVideoUrl && activeStep !== 's8_s10_videos' && <MasterCutQuickBanner finalVideoUrl={props.finalVideoUrl} clipCount={entityMaps.activeGenerationRuns.length} showMasterCutBanner={showMasterCutBanner} onToggleBanner={() => setShowMasterCutBanner((v) => !v)} onInspectClips={() => setActiveStep('s8_s10_videos')} />}
          <StudioWorldToImagesColumn {...ws} />
          <StudioShotsToVideosColumn {...ws} />
        </div>
        <div className={cn('w-full', isLeftRight ? `${contextWidthClass} xl:sticky xl:top-4` : '')}>
          <StudioRightInspectorPane selectedItem={selectedItem} onClearSelection={() => setSelectedItem(null)} canWrite={props.canWrite} busyAction={actions.busyAction} isRunningPipeline={actions.isRunningPipeline} compiledPreviews={actions.compiledPreviews} onCompilePreview={actions.handleCompilePreview} onAppearanceAction={actions.handleAppearanceAction} latestStageRunByStage={stageMaps.latestStageRunByStage} completedStages={stageMaps.completedStages} gatesById={stageMaps.gatesById} activeStep={activeStep} activeAgentCard={activeAgentCard} storyGraph={props.storyGraph} panelSizePct={panelSizePct} onChangePanelSizePct={setPanelSizePct} onSelectStepGroup={(group) => { setExpandAllSteps(false); setActiveStep(group) }} onRunStage={actions.handleRunStage} />
        </div>
      </div>
    </div>
  )
}

export const StoryGraphStudioPanel = (props: StoryGraphStudioPanelProps) => {
  const [activeStep, setActiveStep] = useState<ActiveStepId>('s3_images')
  const [expandAllSteps, setExpandAllSteps] = useState(false)
  const [layoutOrientation, setLayoutOrientation] = useState<StudioLayoutOrientation>('left-right')
  const [panelSizePct, setPanelSizePct] = useState<number>(30)
  const [show3DGraph, setShow3DGraph] = useState(false)
  const [showMasterCutBanner, setShowMasterCutBanner] = useState(true)
  const [designFilter, setDesignFilter] = useState<DesignFilter>('all')
  const [selectedItem, setSelectedItem] = useState<SelectedInspectorItem | null>(null)

  const actions = useStoryGraphStudioActions(props.productionId, props.onGraphUpdated)
  const stageMaps = deriveStageAndGateMaps(props.storyGraph, props.blockedGate, props.pipelineStatus, props.pipelineError, actions.errorMsg)
  const entityMaps = deriveEntityAndAssetMaps(props.storyGraph, designFilter)
  const macroStepCards = useMacroStepCards(props.storyGraph, entityMaps, props.finalVideoUrl)

  return (
    <StoryGraphStudioWorkspace
      props={props} activeStep={activeStep} setActiveStep={setActiveStep} expandAllSteps={expandAllSteps} setExpandAllSteps={setExpandAllSteps}
      layoutOrientation={layoutOrientation} setLayoutOrientation={setLayoutOrientation} panelSizePct={panelSizePct} setPanelSizePct={setPanelSizePct}
      show3DGraph={show3DGraph} setShow3DGraph={setShow3DGraph} showMasterCutBanner={showMasterCutBanner} setShowMasterCutBanner={setShowMasterCutBanner}
      designFilter={designFilter} setDesignFilter={setDesignFilter} selectedItem={selectedItem} setSelectedItem={setSelectedItem}
      actions={actions} stageMaps={stageMaps} entityMaps={entityMaps} macroStepCards={macroStepCards}
    />
  )
}
