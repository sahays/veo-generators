import { createStore, type StoreApi } from 'zustand/vanilla'

/** Most drivers that can be shaded on the timeline at once. */
export const MAX_SELECTED_DRIVERS = 6

/**
 * View state of one Engagement workspace that is not part of the shared
 * timeline kit: which drivers are shaded on the timeline and which metric
 * curves are drawn. One store per workspace, so nothing leaks between records.
 */
export interface EngagementUiState {
  /** Influence keys of the selected drivers, in selection order (the order fixes their colours). */
  selectedDrivers: string[]
  /** Keys of the metrics that are not drawn. At least one metric always stays visible. */
  hiddenMetrics: string[]
  showSmoothed: boolean
  toggleDriver: (key: string) => void
  clearDrivers: () => void
  toggleMetric: (key: string) => void
  setShowSmoothed: (show: boolean) => void
}

export type EngagementUiStore = StoreApi<EngagementUiState>

function toggledDrivers(selected: readonly string[], key: string): string[] {
  if (selected.includes(key)) return selected.filter((entry) => entry !== key)
  return selected.length >= MAX_SELECTED_DRIVERS ? [...selected] : [...selected, key]
}

/** Hide or show a metric; hiding the last visible one is ignored. */
function toggledMetrics(hidden: readonly string[], key: string, metricKeys: readonly string[]): string[] {
  if (hidden.includes(key)) return hidden.filter((entry) => entry !== key)
  const visibleAfter = metricKeys.filter((entry) => entry !== key && !hidden.includes(entry))
  return visibleAfter.length === 0 ? [...hidden] : [...hidden, key]
}

/** `metricKeys` are the keys of the report's metrics. Every metric starts visible. */
export function createEngagementUiStore(metricKeys: readonly string[]): EngagementUiStore {
  return createStore<EngagementUiState>((set) => ({
    selectedDrivers: [],
    hiddenMetrics: [],
    showSmoothed: true,
    toggleDriver: (key) => set((state) => ({ selectedDrivers: toggledDrivers(state.selectedDrivers, key) })),
    clearDrivers: () => set({ selectedDrivers: [] }),
    toggleMetric: (key) => set((state) => ({ hiddenMetrics: toggledMetrics(state.hiddenMetrics, key, metricKeys) })),
    setShowSmoothed: (showSmoothed) => set({ showSmoothed }),
  }))
}
