import { createStore, type StoreApi } from 'zustand/vanilla'
import type { TimeRange } from '@/types/insights'
import type { TimelineItemKind } from '@/types/timeline/model'

/** Most entity lanes that can be pinned to the timeline at once. */
export const MAX_PINNED_ENTITIES = 8

/** A selected timeline item, or a free range dragged on the ruler (`kind: 'range'`). */
export interface TimelineSelection {
  kind: TimelineItemKind | 'range'
  id: string | null
  label: string
  /** Point items have `end_sec === start_sec`. */
  range: TimeRange
}

export interface WorkspaceInit {
  pinnedEntityIds?: string[]
  hiddenLanes?: string[]
  selection?: TimelineSelection | null
}

export interface WorkspaceState {
  selection: TimelineSelection | null
  pinnedEntityIds: string[]
  hiddenLanes: string[]
  search: string
  followPlayhead: boolean
  loopSelection: boolean
  select: (selection: TimelineSelection | null) => void
  togglePin: (entityId: string) => void
  toggleLane: (laneId: string) => void
  setSearch: (search: string) => void
  setFollowPlayhead: (follow: boolean) => void
  setLoopSelection: (loop: boolean) => void
}

export type WorkspaceStore = StoreApi<WorkspaceState>

function toggled(list: readonly string[], value: string, limit = Infinity): string[] {
  if (list.includes(value)) return list.filter((entry) => entry !== value)
  return list.length >= limit ? [...list] : [...list, value]
}

/** The range playback should loop over, or null when looping does not apply. */
export function loopRangeOf(state: Pick<WorkspaceState, 'selection' | 'loopSelection'>): TimeRange | null {
  const range = state.selection?.range
  return state.loopSelection && range && range.end_sec > range.start_sec ? range : null
}

/**
 * State of one timeline workspace (Scene Analysis or Engagement). Each
 * workspace page creates its own store, so two workspaces never share
 * selection, pins or lane visibility, and nothing leaks between records.
 */
export function createWorkspaceStore(init: WorkspaceInit = {}): WorkspaceStore {
  return createStore<WorkspaceState>((set) => ({
    selection: init.selection ?? null,
    pinnedEntityIds: (init.pinnedEntityIds ?? []).slice(0, MAX_PINNED_ENTITIES),
    hiddenLanes: init.hiddenLanes ?? [],
    search: '',
    followPlayhead: true,
    loopSelection: false,
    select: (selection) => set({ selection }),
    togglePin: (entityId) =>
      set((state) => ({ pinnedEntityIds: toggled(state.pinnedEntityIds, entityId, MAX_PINNED_ENTITIES) })),
    toggleLane: (laneId) => set((state) => ({ hiddenLanes: toggled(state.hiddenLanes, laneId) })),
    setSearch: (search) => set({ search }),
    setFollowPlayhead: (followPlayhead) => set({ followPlayhead }),
    setLoopSelection: (loopSelection) => set({ loopSelection }),
  }))
}
