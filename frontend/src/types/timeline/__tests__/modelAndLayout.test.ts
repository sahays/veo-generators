import { describe, expect, it } from 'vitest'
import { categoryLabel, cssSlug, emotionColor, glyphFor, glyphPath } from '../glyphs'
import { buildTimelineModel, listSpeakers, snapshotAt } from '../model'
import { stackMarkers, type PlacedMarker } from '../stacking'
import { computeWindow, estimateRowHeight, prefixOffsets, scrollTopToReveal } from '../windowing'
import { AD_SPOT_RECORD, AD_SPOT_TIMELINE } from './adSpotFixture'

const doc = AD_SPOT_TIMELINE
const model = buildTimelineModel(doc)

describe('fixture matches the timeline.json contract', () => {
  const inBounds = (t: number): boolean => t >= 0 && t <= doc.duration_sec
  const sortedByStart = (items: readonly { start_sec: number }[]): boolean =>
    items.every((item, i) => i === 0 || items[i - 1].start_sec <= item.start_sec)

  it('keeps every list sorted with 1-based ids in order', () => {
    const lists: [string, readonly { id: string; start_sec: number }[]][] = [
      ['seg', doc.segments],
      ['cue', doc.cues],
      ['evt', doc.events],
      ['emo', doc.emotions],
      ['km', doc.key_moments],
      ['nb', doc.narrative_beats],
      ['ad', doc.ad_opportunities ?? []],
    ]
    for (const [prefix, items] of lists) {
      expect(sortedByStart(items)).toBe(true)
      expect(items.map((i) => i.id)).toEqual(items.map((_, i) => `${prefix}-${i + 1}`))
      expect(items.every((i) => inBounds(i.start_sec))).toBe(true)
    }
  })

  it('has contiguous segments covering the whole video, split on the cuts', () => {
    expect(doc.segments[0].start_sec).toBe(0)
    expect(doc.segments[doc.segments.length - 1].end_sec).toBe(doc.duration_sec)
    expect(doc.segments.slice(1).map((s) => s.start_sec)).toEqual(doc.cuts)
    expect(doc.segments.every((s, i) => i === 0 || s.start_sec === doc.segments[i - 1].end_sec)).toBe(true)
  })

  it('orders entities by screen time, which equals the summed appearances', () => {
    const times = doc.entities.map((e) => e.screen_time_sec)
    expect(times).toEqual([...times].sort((a, b) => b - a))
    expect(doc.entities.map((e) => e.id)).toEqual(doc.entities.map((_, i) => `ent-${i + 1}`))
    for (const entity of doc.entities) {
      const summed = entity.appearances.reduce((n, a) => n + (a.end_sec - a.start_sec), 0)
      expect(entity.screen_time_sec).toBeCloseTo(summed, 2)
      expect(sortedByStart(entity.appearances)).toBe(true)
    }
  })

  it('pairs with a record whose counts and duration describe the same document', () => {
    expect(AD_SPOT_RECORD.duration_sec).toBe(doc.duration_sec)
    expect(AD_SPOT_RECORD.counts).toMatchObject({ segments: 9, cues: 20, entities: 9, key_moments: 9 })
    const tiles = AD_SPOT_RECORD.filmstrip
    expect(tiles && tiles.count * tiles.interval_sec).toBe(doc.duration_sec)
    expect(tiles && tiles.columns * tiles.rows).toBeGreaterThanOrEqual(tiles?.count ?? Infinity)
  })
})

describe('snapshotAt', () => {
  it('resolves segment, cue, strongest emotion and who is on screen', () => {
    const snap = snapshotAt(model, 30)
    expect(snap.segment?.title).toBe('Shared laughter on the balcony')
    expect(snap.cue?.speaker).toBe('Mr. Rao')
    expect(snap.emotion?.emotion).toBe('humor')
    expect(snap.entities.map((e) => e.name)).toEqual(['Asha', 'Steel tumblers', 'Balcony', 'Mr. Rao'])
  })

  it('prefers the spoken cue over the music bed that started earlier', () => {
    expect(snapshotAt(model, 35).cue?.id).toBe('cue-17')
    expect(snapshotAt(model, 38.5).cue?.id).toBe('cue-14')
  })

  it('keeps the same key while nothing changes and changes it at a boundary', () => {
    expect(snapshotAt(model, 1.2).key).toBe(snapshotAt(model, 2.9).key)
    expect(snapshotAt(model, 2.9).key).not.toBe(snapshotAt(model, 3.3).key)
  })

  it('resolves the last instant of the video and clamps out-of-range times', () => {
    expect(snapshotAt(model, 45).segment?.id).toBe('seg-9')
    expect(snapshotAt(model, 999).segment?.id).toBe('seg-9')
    expect(snapshotAt(model, -5).segment?.id).toBe('seg-1')
  })

  it('indexes every item by id for selections and deep links', () => {
    expect(model.itemsById.get('km-5')).toMatchObject({ kind: 'moment', range: { start_sec: 30.9, end_sec: 30.9 } })
    expect(model.itemsById.get('ent-2')?.range).toEqual({ start_sec: 12, end_sec: 17.4 })
    expect(model.itemsById.get('ad-2')).toMatchObject({ kind: 'ad_opportunity', range: { start_sec: 12, end_sec: 17.4 } })
    expect(model.itemsById.size).toBe(9 + 20 + 9 + 9 + 10 + 9 + 6 + 4)
    expect(listSpeakers(doc.cues)).toEqual(['Narrator', 'Asha', 'Mr. Rao'])
  })
})

describe('stackMarkers', () => {
  const span = (x: number) => ({ x0: x - 7, x1: x + 7 })
  const overlapsInRow = (placed: PlacedMarker<number>[], gap: number): boolean =>
    placed.some((a) => placed.some((b) => a !== b && a.row === b.row && a.x0 < b.x1 + gap && b.x0 < a.x1 + gap))

  it('puts colliding markers on separate rows and reuses rows once clear', () => {
    const placed = stackMarkers([100, 105, 110, 200], span, { gap: 2, maxRows: 3 })
    expect(placed.map((p) => p.row)).toEqual([0, 1, 2, 0])
    expect(overlapsInRow(placed, 2)).toBe(false)
  })

  it('folds markers into a cluster when every row is taken, losing none', () => {
    const xs = [100, 101, 102, 103, 104, 300]
    const placed = stackMarkers(xs, span, { gap: 2, maxRows: 2 })
    expect(placed).toHaveLength(3)
    expect(placed.flatMap((p) => p.items).sort((a, b) => a - b)).toEqual(xs)
    expect(placed.map((p) => p.items.length)).toEqual([3, 2, 1])
    expect(overlapsInRow(placed, 2)).toBe(false)
  })

  it('never overlaps within a row for dense random input at any row budget', () => {
    let seed = 7
    const next = (): number => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
    const xs = Array.from({ length: 200 }, () => Math.round(next() * 600))
    for (const maxRows of [1, 2, 4]) {
      const placed = stackMarkers(xs, span, { gap: 3, maxRows })
      expect(overlapsInRow(placed, 3)).toBe(false)
      expect(placed.reduce((n, p) => n + p.items.length, 0)).toBe(xs.length)
      expect(Math.max(...placed.map((p) => p.row))).toBeLessThan(maxRows)
    }
  })
})

describe('glyphs', () => {
  it('gives schema categories distinct shape and colour pairs', () => {
    const types = ['hook', 'reveal', 'twist', 'cliffhanger', 'punchline', 'action_peak', 'emotional_peak', 'song', 'product_reveal', 'call_to_action']
    const pairs = new Set(types.map((t) => `${glyphFor(t).shape}/${glyphFor(t).color}`))
    expect(pairs.size).toBe(types.length)
    expect(new Set(types.map((t) => glyphFor(t).shape)).size).toBeGreaterThanOrEqual(6)
  })

  it('maps unknown categories to a stable glyph and builds closed paths', () => {
    expect(glyphFor('Mystery Type')).toEqual(glyphFor('mystery type'))
    expect(glyphPath(glyphFor('mystery type').shape, 6)).toMatch(/^M.*Z$/)
    expect(glyphPath('star', 6).split('L')).toHaveLength(10)
  })

  it('builds theme-token colours and safe slugs for free-text labels', () => {
    expect(emotionColor('Joy')).toMatch(/^var\(--emotion-joy, var\(--chart-[1-8]\)\)$/)
    expect(cssSlug(' Bitter-sweet; }body{ ')).toBe('bitter-sweet-body')
    expect(emotionColor('')).toMatch(/^var\(--chart-[1-8]\)$/)
    expect(categoryLabel('call_to_action')).toBe('Call to action')
  })
})

describe('list windowing', () => {
  const offsets = prefixOffsets(Array.from({ length: 100 }, (_, i) => (i % 2 === 0 ? 40 : 60)))

  it('mounts only rows near the scroll position and pads the rest', () => {
    const win = computeWindow(offsets, 1000, 300, 100)
    expect(win).toEqual({ start: 18, end: 28, padTop: 900, padBottom: 3600 })
    expect(win.padTop + (offsets[win.end] - offsets[win.start]) + win.padBottom).toBe(5000)
  })

  it('clamps at both ends and handles an empty list', () => {
    expect(computeWindow(offsets, 0, 300, 100)).toMatchObject({ start: 0, padTop: 0 })
    expect(computeWindow(offsets, 99999, 300, 100)).toMatchObject({ end: 100, padBottom: 0 })
    expect(computeWindow(prefixOffsets([]), 0, 300, 100)).toEqual({ start: 0, end: 0, padTop: 0, padBottom: 0 })
  })

  it('only scrolls to follow a row that is out of view', () => {
    expect(scrollTopToReveal(offsets, 20, 1000, 300)).toBeNull()
    expect(scrollTopToReveal(offsets, 60, 1000, 300)).toBe(2900)
    expect(scrollTopToReveal(offsets, 0, 1000, 300)).toBe(0)
    expect(scrollTopToReveal(offsets, 500, 1000, 300)).toBeNull()
  })

  it('estimates taller rows for longer text', () => {
    expect(estimateRowHeight(10, 60, 18, 28)).toBe(46)
    expect(estimateRowHeight(130, 60, 18, 28)).toBe(82)
    expect(estimateRowHeight(0, 0, 18, 28)).toBe(46)
  })
})
