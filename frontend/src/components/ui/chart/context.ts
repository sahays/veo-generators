import * as React from 'react'
import type { ChartConfig } from './config'

export type ChartContextValue = {
  config: ChartConfig
}

export const ChartContext = React.createContext<ChartContextValue | null>(null)

/** Read the config of the enclosing `ChartContainer`; throws when rendered outside one. */
export function useChart(): ChartContextValue {
  const context = React.useContext(ChartContext)
  if (!context) {
    throw new Error('useChart must be used within a ChartContainer')
  }
  return context
}
