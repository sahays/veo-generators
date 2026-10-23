import { useState, useEffect, useRef, type ReactNode } from 'react'
import type { Project, StoryGraphData } from '@/types/project'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  deriveStageAndGateMaps,
  deriveEntityAndAssetMaps,
  useMacroStepCards,
  useStoryGraphStudioActions,
  type DesignFilter,
  type SelectedInspectorItem,
} from './storygraph/storyGraphStudioTypes'
import { StudioInspectorDrawer } from './storygraph/StudioRightInspectorPane'
import { allEntities } from './storygraph/details/snapshotSelectors'
import { RegenerateCascadeDialog } from './storygraph/cascade/RegenerateCascadeDialog'
import { StudioHeader } from './storygraph/shell/StudioHeader'
import { StudioIssueBanner } from './storygraph/shell/StudioIssueBanner'
import { StudioStepAccordion } from './storygraph/shell/StudioStepAccordion'
import { StudioAdvancedPanel } from './storygraph/shell/StudioAdvancedPanel'
import { renderStepSection, type StepSectionContext } from './storygraph/shell/stepSections'
import { useStudioController, type StudioTab } from './storygraph/shell/useStudioController'

interface StoryGraphStudioPanelProps {
  productionId: string
  storyGraph?: StoryGraphData
  currentStage?: string
  pipelineStatus?: string
  pipelineError?: string | null
  blockedGate?: string | null
  finalVideoUrl?: string
  renderQuality?: 'draft' | 'final'
  videoResolution?: '360p' | '720p' | '1080p'
  canWrite: boolean
  onGraphUpdated: (snapshot: Project) => void
  /** Header copy supplied by the page. */
  title?: string
  subtitle?: string
  meta?: string[]
  /** Usage/cost breakdown, shown under Advanced. */
  usage?: ReactNode
  onBack?: () => void
  onEditBrief?: () => void
}

type Controller = ReturnType<typeof useStudioController>

interface WorkspaceProps {
  props: StoryGraphStudioPanelProps
  ctrl: Controller
  ctx: StepSectionContext
  stageMaps: ReturnType<typeof deriveStageAndGateMaps>
}

const StudioTabs = ({ props, ctrl, ctx, stageMaps }: WorkspaceProps) => (
  <Tabs value={ctrl.tab} onValueChange={(v) => ctrl.setTab(v as StudioTab)}>
    <TabsList>
      <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
      <TabsTrigger value="advanced">Advanced</TabsTrigger>
    </TabsList>
    <TabsContent value="pipeline">
      <StudioStepAccordion items={ctrl.stepItems} isExpanded={ctrl.isExpanded} onToggle={ctrl.toggle} renderStep={(id) => renderStepSection(id, ctx)} />
    </TabsContent>
    <TabsContent value="advanced">
      <StudioAdvancedPanel
        storyGraph={props.storyGraph} canWrite={props.canWrite} completedStages={stageMaps.completedStages} busyAction={ctx.actions.busyAction}
        latestStageRunByStage={stageMaps.latestStageRunByStage} usage={props.usage} onAppearanceAction={ctx.actions.handleAppearanceAction}
        onSelectStepGroup={(g) => { ctrl.setTab('pipeline'); ctrl.focus(g) }}
      />
    </TabsContent>
  </Tabs>
)

const StudioWorkspace = ({ props, ctrl, ctx, stageMaps }: WorkspaceProps) => {
  const { actions } = ctx
  const hasBlockingShots = props.pipelineStatus === 'needs_review' || (props.storyGraph?.shots || []).some((s) => s.needs_manual_edit)
  return (
    <div className="w-full space-y-5">
      <RegenerateCascadeDialog
        request={actions.cascade.pendingRequest} hasBlockingShots={hasBlockingShots}
        onConfirm={() => void actions.cascade.confirmCascade()} onCancel={actions.cascade.cancelCascade}
      />
      <StudioHeader
        title={props.title || 'Production studio'} subtitle={props.subtitle} meta={props.meta || []} status={ctrl.status} progress={ctrl.progress}
        canWrite={props.canWrite} nextAction={ctrl.nextAction} onNextAction={ctrl.onNextAction} menuItems={ctrl.menuItems} onBack={props.onBack}
      />
      {stageMaps.activeError && (
        <StudioIssueBanner
          message={stageMaps.activeError} stage={actions.failedStage} canRetry={props.canWrite}
          isBusy={actions.busyAction !== null || actions.isRunningPipeline} onRetry={actions.handleRetryStage} onDismiss={() => actions.setErrorMsg(null)}
        />
      )}
      <StudioTabs props={props} ctrl={ctrl} ctx={ctx} stageMaps={stageMaps} />
      <StudioInspectorDrawer
        productionId={props.productionId} selectedItem={ctx.selectedItem} onClose={() => ctx.setSelectedItem(null)} canWrite={props.canWrite} busyAction={actions.busyAction}
        compiledPreviews={actions.compiledPreviews} onCompilePreview={actions.handleCompilePreview} onAppearanceAction={actions.handleAppearanceAction} storyGraph={props.storyGraph}
      />
    </div>
  )
}

function useAutoStart(props: StoryGraphStudioPanelProps, completedCount: number, runForward: () => Promise<void>) {
  const autoStartedRef = useRef(false)
  useEffect(() => {
    const hasEntities = allEntities(props.storyGraph).length > 0
    if (props.canWrite && !autoStartedRef.current && !hasEntities && completedCount <= 1) {
      autoStartedRef.current = true
      void runForward()
    }
  }, [props.canWrite, props.storyGraph, completedCount, runForward])
}

export const StoryGraphStudioPanel = (props: StoryGraphStudioPanelProps) => {
  const [designFilter, setDesignFilter] = useState<DesignFilter>('all')
  const [selectedItem, setSelectedItem] = useState<SelectedInspectorItem | null>(null)
  const baseMaps = deriveStageAndGateMaps(props.storyGraph, props.blockedGate, props.pipelineStatus, props.pipelineError, null)
  const actions = useStoryGraphStudioActions(props.productionId, props.onGraphUpdated, baseMaps.completedStages)
  const stageMaps = deriveStageAndGateMaps(props.storyGraph, props.blockedGate, props.pipelineStatus, props.pipelineError, actions.errorMsg)
  const entityMaps = deriveEntityAndAssetMaps(props.storyGraph, designFilter)
  const cards = useMacroStepCards(props.storyGraph, entityMaps, props.finalVideoUrl)
  const ctrl = useStudioController({
    storyGraph: props.storyGraph, pipelineStatus: props.pipelineStatus, finalVideoUrl: props.finalVideoUrl, renderQuality: props.renderQuality,
    canWrite: props.canWrite, onEditBrief: props.onEditBrief, actions, stageMaps, cards,
  })
  useAutoStart(props, stageMaps.completedStages.size, actions.handleRunForward)
  const ctx: StepSectionContext = {
    productionId: props.productionId, storyGraph: props.storyGraph, canWrite: props.canWrite, pipelineStatus: props.pipelineStatus,
    finalVideoUrl: props.finalVideoUrl, renderQuality: props.renderQuality, videoResolution: props.videoResolution, onGraphUpdated: props.onGraphUpdated,
    actions, entityMaps, designFilter, setDesignFilter, selectedItem, setSelectedItem,
  }
  return <StudioWorkspace props={props} ctrl={ctrl} ctx={ctx} stageMaps={stageMaps} />
}
