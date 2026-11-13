import { describe, expect, it } from 'vitest'
import { MediaClock, type FrameScheduler, type MediaLike } from '../mediaClock'
import { MAX_PINNED_ENTITIES, createWorkspaceStore, loopRangeOf } from '../workspaceStore'

/** Minimal stand-in for a <video> element whose events the test fires by hand. */
class FakeMedia implements MediaLike {
  currentTime = 0
  playbackRate = 1
  muted = false
  duration = Number.NaN
  paused = true
  playCalls = 0
  private readonly listeners = new Map<string, Set<() => void>>()

  play(): void {
    this.playCalls += 1
    this.paused = false
    this.emit('play')
  }

  pause(): void {
    this.paused = true
    this.emit('pause')
  }

  addEventListener(type: string, listener: () => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)?.add(listener)
  }

  removeEventListener(type: string, listener: () => void): void {
    this.listeners.get(type)?.delete(listener)
  }

  emit(type: string): void {
    this.listeners.get(type)?.forEach((listener) => listener())
  }

  load(duration: number): void {
    this.duration = duration
    this.emit('loadedmetadata')
  }

  listenerCount(): number {
    return [...this.listeners.values()].reduce((n, set) => n + set.size, 0)
  }
}

/** Frame scheduler the test advances explicitly. */
class ManualFrames implements FrameScheduler {
  private queue = new Map<number, () => void>()
  private nextHandle = 1

  request = (callback: () => void): number => {
    this.queue.set(this.nextHandle, callback)
    return this.nextHandle++
  }

  cancel = (handle: number): void => {
    this.queue.delete(handle)
  }

  get pending(): number {
    return this.queue.size
  }

  flush(): void {
    const callbacks = [...this.queue.values()]
    this.queue.clear()
    callbacks.forEach((callback) => callback())
  }
}

function setup(duration = 45): { clock: MediaClock; media: FakeMedia; frames: ManualFrames } {
  const frames = new ManualFrames()
  const clock = new MediaClock(duration, frames)
  const media = new FakeMedia()
  clock.attach(media)
  media.load(duration)
  return { clock, media, frames }
}

describe('MediaClock', () => {
  it('seeks without changing the play state and notifies immediately', () => {
    const { clock, media } = setup()
    const seen: number[] = []
    clock.subscribeTime(() => seen.push(clock.getTime()))

    clock.seek(12.5)
    expect(media.currentTime).toBe(12.5)
    expect(media.paused).toBe(true)
    expect(seen).toEqual([12.5])

    media.play()
    clock.seek(20)
    expect(media.paused).toBe(false)
    expect(clock.getState().playing).toBe(true)

    clock.seek(5, { play: false })
    expect(media.paused).toBe(true)
    clock.seek(6, { play: true })
    expect(media.paused).toBe(false)
  })

  it('clamps seeks to the media duration', () => {
    const { clock, media } = setup(45)
    clock.seek(999)
    expect(media.currentTime).toBe(45)
    clock.seek(-3)
    expect(media.currentTime).toBe(0)
    clock.seek(Number.NaN)
    expect(clock.getTime()).toBe(0)
  })

  it('holds a seek made before metadata loads and applies it once ready', () => {
    const frames = new ManualFrames()
    const clock = new MediaClock(45, frames)
    const media = new FakeMedia()
    clock.attach(media)
    expect(clock.getState()).toMatchObject({ ready: false, duration: 45 })

    clock.seek(30)
    expect(clock.getTime()).toBe(30)
    expect(media.currentTime).toBe(0)
    media.emit('timeupdate')
    expect(clock.getTime()).toBe(30)

    media.load(44.96)
    expect(media.currentTime).toBe(30)
    expect(clock.getState()).toMatchObject({ ready: true, duration: 44.96 })
  })

  it('ticks once per frame only while playing', () => {
    const { clock, media, frames } = setup()
    let ticks = 0
    clock.subscribeTime(() => ticks++)
    expect(frames.pending).toBe(0)

    media.play()
    expect(frames.pending).toBe(1)
    media.currentTime = 0.04
    frames.flush()
    media.currentTime = 0.08
    frames.flush()
    expect(ticks).toBe(2)
    expect(clock.getTime()).toBe(0.08)

    media.pause()
    expect(frames.pending).toBe(0)
    media.currentTime = 0.5
    frames.flush()
    expect(ticks).toBe(2)
  })

  it('does not notify state listeners for time changes', () => {
    const { clock, media, frames } = setup()
    let stateChanges = 0
    clock.subscribeState(() => stateChanges++)
    media.play()
    media.currentTime = 1
    frames.flush()
    media.emit('timeupdate')
    expect(stateChanges).toBe(1)
    const before = clock.getState()
    media.emit('timeupdate')
    expect(clock.getState()).toBe(before)

    media.playbackRate = 1.5
    media.emit('ratechange')
    expect(clock.getState().rate).toBe(1.5)
    expect(stateChanges).toBe(2)

    clock.setMuted(true)
    expect(media.muted).toBe(true)
    expect(clock.getState().muted).toBe(true)
    expect(stateChanges).toBe(3)
  })

  it('wraps to the loop start when playback runs off the end of the range', () => {
    const { clock, media, frames } = setup()
    clock.setLoop({ start_sec: 10, end_sec: 12 })
    clock.seek(11.9, { play: true })
    media.currentTime = 12.03
    frames.flush()
    expect(media.currentTime).toBe(10)
    expect(clock.getTime()).toBe(10)
  })

  it('does not pull playback back when the user seeks outside the loop', () => {
    const { clock, media, frames } = setup()
    clock.setLoop({ start_sec: 10, end_sec: 12 })
    clock.seek(30, { play: true })
    media.currentTime = 30.04
    frames.flush()
    expect(media.currentTime).toBe(30.04)
  })

  it('restarts a loop that ends with the media when the element fires ended', () => {
    const { clock, media, frames } = setup(45)
    clock.setLoop({ start_sec: 39, end_sec: 45 })
    clock.seek(44.9, { play: true })
    media.currentTime = 45
    media.paused = true
    media.emit('ended')
    expect(media.currentTime).toBe(39)
    expect(media.paused).toBe(false)
    expect(frames.pending).toBe(1)
  })

  it('ignores empty loop ranges and clears the loop with null', () => {
    const { clock } = setup()
    clock.setLoop({ start_sec: 5, end_sec: 5 })
    expect(clock.getState().loop).toBeNull()
    clock.setLoop({ start_sec: 5, end_sec: 6 })
    expect(clock.getState().loop).toEqual({ start_sec: 5, end_sec: 6 })
    clock.setLoop(null)
    expect(clock.getState().loop).toBeNull()
  })

  it('releases every listener and stops ticking when detached', () => {
    const { clock, media, frames } = setup()
    media.play()
    expect(media.listenerCount()).toBeGreaterThan(0)
    clock.attach(null)
    expect(media.listenerCount()).toBe(0)
    expect(frames.pending).toBe(0)
    expect(clock.getState().playing).toBe(false)
    clock.seek(7)
    expect(clock.getTime()).toBe(7)
  })

  it('survives a rejected play() promise', async () => {
    const { clock, media } = setup()
    media.play = () => Promise.reject(new Error('NotAllowedError'))
    clock.play()
    await Promise.resolve()
    expect(clock.getState().playing).toBe(false)
  })
})

describe('workspace store', () => {
  it('keeps separate state per workspace instance', () => {
    const a = createWorkspaceStore()
    const b = createWorkspaceStore({ pinnedEntityIds: ['ent-9'] })
    a.getState().togglePin('ent-1')
    a.getState().setSearch('chai')
    expect(a.getState().pinnedEntityIds).toEqual(['ent-1'])
    expect(b.getState().pinnedEntityIds).toEqual(['ent-9'])
    expect(b.getState().search).toBe('')
  })

  it('toggles pins and refuses to exceed the lane cap', () => {
    const store = createWorkspaceStore()
    for (let i = 0; i < MAX_PINNED_ENTITIES + 3; i++) store.getState().togglePin(`ent-${i}`)
    expect(store.getState().pinnedEntityIds).toHaveLength(MAX_PINNED_ENTITIES)
    expect(store.getState().pinnedEntityIds).not.toContain(`ent-${MAX_PINNED_ENTITIES}`)
    store.getState().togglePin('ent-0')
    expect(store.getState().pinnedEntityIds).not.toContain('ent-0')
    store.getState().togglePin('ent-new')
    expect(store.getState().pinnedEntityIds).toContain('ent-new')
  })

  it('toggles lane visibility', () => {
    const store = createWorkspaceStore({ hiddenLanes: ['density'] })
    store.getState().toggleLane('density')
    store.getState().toggleLane('filmstrip')
    expect(store.getState().hiddenLanes).toEqual(['filmstrip'])
  })

  it('loops only a selected range with length when looping is on', () => {
    const store = createWorkspaceStore()
    const range = { start_sec: 12, end_sec: 17.4 }
    store.getState().select({ kind: 'segment', id: 'seg-4', label: 'Reveal', range })
    expect(loopRangeOf(store.getState())).toBeNull()
    store.getState().setLoopSelection(true)
    expect(loopRangeOf(store.getState())).toEqual(range)
    store.getState().select({ kind: 'moment', id: 'km-2', label: 'Pack', range: { start_sec: 13.1, end_sec: 13.1 } })
    expect(loopRangeOf(store.getState())).toBeNull()
    store.getState().select(null)
    expect(loopRangeOf(store.getState())).toBeNull()
  })
})
