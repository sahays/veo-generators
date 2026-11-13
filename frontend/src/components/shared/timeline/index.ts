/**
 * Timeline kit: shared building blocks for the Scene Analysis and Engagement
 * workspaces. See `frontend/src/components/shared/timeline/README.md`.
 */
export { TimelineWorkspace, type TimelineWorkspaceProps } from './TimelineWorkspace'
export { TimelineSurface, type TimelineSurfaceProps } from './TimelineSurface'
export { TimelineLane, LaneSvg, LaneItem, type TimelineLaneProps, type LaneRenderArgs, type LaneSvgProps, type LaneItemProps } from './TimelineLane'
export { TimelineToolbar, LaneToggleMenu, ZoomControls, type LaneOption, type TimelineToolbarProps } from './TimelineToolbar'
export { Minimap, type MinimapProps } from './Minimap'
export { MomentHoverCard, NowStrip, type MomentHoverCardProps, type NowStripProps } from './MomentSummary'
export { LANE_HEIGHT, TIMELINE_GUTTER_PX } from './layout'
export { RulerLane } from './lanes/RulerLane'
export { FilmstripLane, type FilmstripLaneProps } from './lanes/FilmstripLane'
export { SegmentsLane, type SegmentsLaneProps } from './lanes/SegmentsLane'
export { RangeLane, EmotionsLane, BeatsLane, intensityOpacity, type RangeLaneProps, type RangeStyle } from './lanes/RangeLane'
export { MarkersLane, KeyMomentsLane, type MarkersLaneProps, type MarkerStyle, type KeyMomentsLaneProps } from './lanes/MarkersLane'
export { EntityLanes, ENTITY_LANES_ID, type EntityLanesProps } from './lanes/EntityLanes'
export { DensityLane, type DensityLaneProps } from './lanes/DensityLane'
export { GlyphIcon, type GlyphIconProps } from './lanes/GlyphIcon'
export { spanBox, spokenRange, type SpanBox } from './lanes/laneGeometry'
export { SyncedVideoPlayer, type SyncedVideoPlayerProps } from './player/SyncedVideoPlayer'
export { PlayerControls, type PlayerControlsProps } from './player/PlayerControls'
export { TranscriptPanel, type TranscriptPanelProps } from './panels/TranscriptPanel'
export { EntityBrowser, type EntityBrowserProps } from './panels/EntityBrowser'
export { PanelSearch, Highlighted, type PanelSearchProps } from './panels/PanelSearch'
export { JobProgress, JobRetryPanel, type JobProgressProps, type JobRetryPanelProps, type JobStage } from './record/JobProgress'
export {
  BackLink,
  DownloadMenu,
  DurationPill,
  LoadFailure,
  LoadingNotice,
  RecordHeader,
  RecordStatusPill,
  RecordUnavailable,
  type DownloadGroup,
  type DownloadItem,
  type RecordHeaderProps,
  type RecordUnavailableProps,
} from './record/RecordChrome'
