import { createContext, useContext, useState } from 'react'
import { useStore } from 'zustand'
import { createEngagementUiStore, type EngagementUiState, type EngagementUiStore } from '@/store/timeline/engagementUiStore'
import type { ReportModel } from '@/types/engagement/reportModel'

/** Colours of the selected drivers, by selection order. Kept apart from the metric and marker colours. */
const DRIVER_COLORS = ['var(--chart-5)', 'var(--chart-8)', 'var(--chart-4)', 'var(--chart-7)', 'var(--chart-2)', 'var(--chart-6)']

const EngagementUiContext = createContext<EngagementUiStore | null>(null)

export interface EngagementUiProviderProps {
  report: ReportModel
  children: React.ReactNode
}

/** Creates the view state of one Engagement workspace (selected drivers, visible metrics). */
export function EngagementUiProvider({ report, children }: EngagementUiProviderProps): JSX.Element {
  const [store] = useState(() => createEngagementUiStore(report.metrics.map((metric) => metric.key)))
  return <EngagementUiContext.Provider value={store}>{children}</EngagementUiContext.Provider>
}

export function useEngagementUiStore(): EngagementUiStore {
  const store = useContext(EngagementUiContext)
  if (!store) throw new Error('useEngagementUi is only available inside <EngagementUiProvider>')
  return store
}

/** Subscribe to a slice of the workspace's view state. */
export function useEngagementUi<T>(selector: (state: EngagementUiState) => T): T {
  return useStore(useEngagementUiStore(), selector)
}

/** Colour of the driver at `position` in the selection. */
export function driverColor(position: number): string {
  return DRIVER_COLORS[position % DRIVER_COLORS.length]
}
