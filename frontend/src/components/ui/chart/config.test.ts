import { describe, expect, it } from 'vitest'
import { buildColorVars, getPayloadConfig, pickKey, type ChartConfig } from './config'

const config: ChartConfig = {
  desktop: { label: 'Desktop', color: 'var(--chart-1)' },
  mobile: { label: 'Mobile', theme: { light: '#0284C7', dark: '#38BDF8' } },
  chrome: { label: 'Chrome' },
}

describe('buildColorVars', () => {
  it('emits a theme-following light-dark() expression for themed series and skips colourless ones', () => {
    expect(buildColorVars(config)).toEqual({
      '--color-desktop': 'var(--chart-1)',
      '--color-mobile': 'light-dark(#0284C7, #38BDF8)',
    })
  })

  it('pins themed series to the requested theme and leaves plain colours untouched', () => {
    expect(buildColorVars(config, 'dark')).toEqual({
      '--color-desktop': 'var(--chart-1)',
      '--color-mobile': '#38BDF8',
    })
    expect(buildColorVars(config, 'light')['--color-mobile']).toBe('#0284C7')
  })
})

describe('getPayloadConfig', () => {
  it('uses the key itself as the series when the item has no such string field', () => {
    const item = { name: 'desktop', dataKey: 'desktop', value: 186, payload: { month: 'Jan', desktop: 186 } }
    expect(getPayloadConfig(config, item, 'desktop')).toBe(config.desktop)
  })

  it('follows a name field on the item before one on the underlying datum', () => {
    const item = { name: 'mobile', dataKey: 'visitors', payload: { name: 'chrome', visitors: 275 } }
    expect(getPayloadConfig(config, item, 'name')).toBe(config.mobile)
  })

  it('follows a name field on the underlying datum (pie charts with nameKey)', () => {
    const item = { dataKey: 'visitors', value: 275, payload: { browser: 'chrome', visitors: 275 } }
    expect(getPayloadConfig(config, item, 'browser')).toBe(config.chrome)
  })

  it('returns undefined for unknown series, non-objects and prototype property names', () => {
    expect(getPayloadConfig(config, { dataKey: 'tablet' }, 'tablet')).toBeUndefined()
    expect(getPayloadConfig(config, null, 'desktop')).toBeUndefined()
    expect(getPayloadConfig(config, { payload: { browser: 'constructor' } }, 'browser')).toBeUndefined()
    expect(getPayloadConfig(config, { dataKey: 'toString' }, 'toString')).toBeUndefined()
  })
})

describe('pickKey', () => {
  it('skips empty strings and accessor functions, keeps zero, and falls back to "value"', () => {
    expect(pickKey(undefined, '', 'mobile')).toBe('mobile')
    expect(pickKey((row: { desktop: number }) => row.desktop, 'desktop')).toBe('desktop')
    expect(pickKey(undefined, 0)).toBe('0')
    expect(pickKey(undefined, () => 1)).toBe('value')
  })
})
