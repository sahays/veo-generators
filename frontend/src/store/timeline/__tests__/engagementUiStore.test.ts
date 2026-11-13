import { describe, expect, it } from 'vitest'
import { MAX_SELECTED_DRIVERS, createEngagementUiStore } from '../engagementUiStore'

describe('engagement UI store: drivers', () => {
  it('keeps selection order, which fixes each driver colour, and removes on a second toggle', () => {
    const store = createEngagementUiStore(['tvr'])
    store.getState().toggleDriver('character:asha')
    store.getState().toggleDriver('emotion:humor')
    store.getState().toggleDriver('character:asha')
    store.getState().toggleDriver('character:asha')
    expect(store.getState().selectedDrivers).toEqual(['emotion:humor', 'character:asha'])
  })

  it('ignores a selection beyond the limit but still allows deselecting', () => {
    const store = createEngagementUiStore(['tvr'])
    for (let i = 0; i <= MAX_SELECTED_DRIVERS; i++) store.getState().toggleDriver(`object:${i}`)
    expect(store.getState().selectedDrivers).toHaveLength(MAX_SELECTED_DRIVERS)
    expect(store.getState().selectedDrivers).not.toContain(`object:${MAX_SELECTED_DRIVERS}`)
    store.getState().toggleDriver('object:0')
    expect(store.getState().selectedDrivers).toHaveLength(MAX_SELECTED_DRIVERS - 1)
    store.getState().clearDrivers()
    expect(store.getState().selectedDrivers).toEqual([])
  })
})

describe('engagement UI store: metrics', () => {
  it('hides and shows metrics but never hides the last visible one', () => {
    const store = createEngagementUiStore(['tvr', 'impressions', 'reach'])
    store.getState().toggleMetric('tvr')
    store.getState().toggleMetric('reach')
    expect(store.getState().hiddenMetrics).toEqual(['tvr', 'reach'])
    store.getState().toggleMetric('impressions')
    expect(store.getState().hiddenMetrics).toEqual(['tvr', 'reach'])
    store.getState().toggleMetric('tvr')
    expect(store.getState().hiddenMetrics).toEqual(['reach'])
  })

  it('cannot hide the only metric of a single-metric report', () => {
    const store = createEngagementUiStore(['engagement_index'])
    store.getState().toggleMetric('engagement_index')
    expect(store.getState().hiddenMetrics).toEqual([])
  })

  it('creates independent stores, so two workspaces never share state', () => {
    const first = createEngagementUiStore(['a', 'b'])
    const second = createEngagementUiStore(['a', 'b'])
    first.getState().toggleDriver('character:asha')
    first.getState().setShowSmoothed(false)
    expect(second.getState().selectedDrivers).toEqual([])
    expect(second.getState().showSmoothed).toBe(true)
  })
})
