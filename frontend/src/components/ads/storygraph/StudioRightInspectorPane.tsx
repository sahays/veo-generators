import { Sheet } from '@/components/ui/sheet'
import type { StoryGraphData } from '@/types/project'
import type { CompiledShotPreview, SelectedInspectorItem } from './storyGraphStudioTypes'
import {
  AppearanceInspectorView,
  ShotAndEntityInspectorView,
  VideoRunInspectorView,
} from './StudioInspectorItemViews'

const KIND_TITLES: Record<SelectedInspectorItem['kind'], string> = {
  stage: 'Step details',
  entity: 'Entity',
  scene: 'Scene',
  appearance: 'Reference sheet',
  shot: 'Shot',
  video_run: 'Video clip',
}

export interface StudioInspectorDrawerProps {
  selectedItem: SelectedInspectorItem | null
  onClose: () => void
  canWrite: boolean
  busyAction: string | null
  compiledPreviews: Record<string, CompiledShotPreview>
  onCompilePreview: (shotId: string) => void
  onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
  storyGraph?: StoryGraphData
}

const InspectorBody = (p: StudioInspectorDrawerProps & { selectedItem: SelectedInspectorItem }) => {
  const item = p.selectedItem
  if (item.kind === 'appearance') {
    return <AppearanceInspectorView item={item} canWrite={p.canWrite} busyAction={p.busyAction} onAppearanceAction={p.onAppearanceAction} />
  }
  if (item.kind === 'video_run') return <VideoRunInspectorView item={item} />
  if (item.kind === 'shot' || item.kind === 'entity' || item.kind === 'scene') {
    return (
      <ShotAndEntityInspectorView
        selectedItem={item}
        busyAction={p.busyAction}
        compiledPreviews={p.compiledPreviews}
        onCompilePreview={p.onCompilePreview}
        scenes={p.storyGraph?.scenes}
      />
    )
  }
  return <p className="text-sm text-muted-foreground">Select an item in a step to see its details.</p>
}

/** On-demand details drawer (replaces the always-visible right inspector pane). */
export const StudioInspectorDrawer = (p: StudioInspectorDrawerProps) => (
  <Sheet
    open={p.selectedItem !== null && p.selectedItem.kind !== 'stage'}
    onClose={p.onClose}
    title={p.selectedItem ? KIND_TITLES[p.selectedItem.kind] : 'Details'}
    subtitle={p.selectedItem?.id}
  >
    {p.selectedItem && <InspectorBody {...p} selectedItem={p.selectedItem} />}
  </Sheet>
)
