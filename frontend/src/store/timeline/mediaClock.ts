import type { TimeRange } from '@/types/insights'

/** The part of `HTMLMediaElement` the clock uses; lets tests drive it with a fake. */
export interface MediaLike {
  currentTime: number
  playbackRate: number
  muted: boolean
  readonly duration: number
  readonly paused: boolean
  play: () => Promise<void> | void
  pause: () => void
  addEventListener: (type: string, listener: () => void) => void
  removeEventListener: (type: string, listener: () => void) => void
}

export interface FrameScheduler {
  request: (callback: () => void) => number
  cancel: (handle: number) => void
}

export interface ClockState {
  playing: boolean
  rate: number
  muted: boolean
  duration: number
  /** True once the media element knows its duration. */
  ready: boolean
  loop: TimeRange | null
}

export interface SeekOptions {
  /** `true` starts playback, `false` pauses; omitted leaves playback as it is. */
  play?: boolean
}

type Listener = () => void

const MEDIA_EVENTS = [
  'timeupdate',
  'seeking',
  'seeked',
  'play',
  'playing',
  'pause',
  'ended',
  'ratechange',
  'volumechange',
  'durationchange',
  'loadedmetadata',
] as const

type MediaEventType = (typeof MEDIA_EVENTS)[number]

/** How close to the end of the media a loop's end must be to wrap on `ended`. */
const END_TOLERANCE_SEC = 0.25

const browserFrames: FrameScheduler = {
  request: (callback) => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(callback) : 0),
  cancel: (handle) => {
    if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(handle)
  },
}

/**
 * Single source of truth for media time, outside React.
 *
 * - Time listeners fire once per animation frame while playing and
 *   immediately on every seek. They are meant for imperative updates (moving
 *   the playhead with a transform) and for `useSyncExternalStore` selectors.
 * - State listeners fire only when play state, rate, duration or loop change.
 * - `seek` never changes the play state unless asked to.
 * - A loop wraps only when playback runs off the end of the range, so seeking
 *   elsewhere while a loop is set plays on from there.
 */
export class MediaClock {
  private media: MediaLike | null = null
  private time = 0
  private pendingSeek: number | null = null
  private frame: number | null = null
  private state: ClockState
  private readonly timeListeners = new Set<Listener>()
  private readonly stateListeners = new Set<Listener>()
  private readonly handlers = MEDIA_EVENTS.map((type) => ({ type, listener: () => this.onMediaEvent(type) }))

  constructor(
    private durationHint = 0,
    private readonly frames: FrameScheduler = browserFrames,
  ) {
    this.state = { playing: false, rate: 1, muted: false, duration: Math.max(durationHint, 0), ready: false, loop: null }
  }

  /** Bind to a media element (ref callback). Pass null to release it. */
  attach = (media: MediaLike | null): void => {
    if (media === this.media) return
    this.detach()
    this.media = media
    if (!media) return
    this.handlers.forEach(({ type, listener }) => media.addEventListener(type, listener))
    this.onMediaEvent('loadedmetadata')
  }

  getTime = (): number => this.time

  getState = (): ClockState => this.state

  subscribeTime = (listener: Listener): (() => void) => {
    this.timeListeners.add(listener)
    return () => this.timeListeners.delete(listener)
  }

  subscribeState = (listener: Listener): (() => void) => {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  /** Fallback duration (from the record) used until the media reports its own. */
  setDurationHint(duration: number): void {
    this.durationHint = duration
    this.syncState()
  }

  seek(timeSec: number, options: SeekOptions = {}): void {
    const target = Math.min(Math.max(Number.isFinite(timeSec) ? timeSec : 0, 0), this.state.duration)
    if (this.media && this.state.ready) this.media.currentTime = target
    else this.pendingSeek = target
    this.setTime(target)
    if (options.play === true) this.play()
    if (options.play === false) this.pause()
  }

  play(): void {
    const result = this.media?.play()
    // Autoplay policies may reject; the element stays paused and `pause` state stands.
    if (result instanceof Promise) result.catch(() => undefined)
  }

  pause(): void {
    this.media?.pause()
  }

  toggle(): void {
    if (this.state.playing) this.pause()
    else this.play()
  }

  setRate(rate: number): void {
    if (!this.media || !(rate > 0)) return
    this.media.playbackRate = rate
    this.syncState()
  }

  setMuted(muted: boolean): void {
    if (!this.media) return
    this.media.muted = muted
    this.syncState()
  }

  /** Loop playback inside `range`; null clears the loop. Empty ranges are ignored. */
  setLoop(range: TimeRange | null): void {
    const loop = range && range.end_sec > range.start_sec ? range : null
    if (loop?.start_sec === this.state.loop?.start_sec && loop?.end_sec === this.state.loop?.end_sec) return
    this.state = { ...this.state, loop }
    this.stateListeners.forEach((listener) => listener())
  }

  private detach(): void {
    const media = this.media
    if (media) this.handlers.forEach(({ type, listener }) => media.removeEventListener(type, listener))
    this.media = null
    this.stopFrames()
    this.syncState()
  }

  private onMediaEvent(type: MediaEventType): void {
    if (type === 'ended' && this.restartLoopAtMediaEnd()) return
    this.syncState()
    this.applyPendingSeek()
    if (this.media && this.pendingSeek === null) this.setTime(this.media.currentTime)
    if (this.state.playing) this.startFrames()
    else this.stopFrames()
  }

  /** True while the last known time lies inside the loop range. */
  private insideLoop(loop: TimeRange): boolean {
    return this.time >= loop.start_sec && this.time < loop.end_sec
  }

  /** A loop reaching the very end of the media ends playback before a frame can wrap it. */
  private restartLoopAtMediaEnd(): boolean {
    const loop = this.state.loop
    if (!loop || !this.media || loop.end_sec < this.state.duration - END_TOLERANCE_SEC) return false
    if (!this.insideLoop(loop) && this.time < loop.end_sec) return false
    this.media.currentTime = loop.start_sec
    this.setTime(loop.start_sec)
    this.play()
    return true
  }

  private applyPendingSeek(): void {
    if (this.pendingSeek === null || !this.media || !this.state.ready) return
    const target = Math.min(this.pendingSeek, this.state.duration)
    this.pendingSeek = null
    this.media.currentTime = target
    this.setTime(target)
  }

  private syncState(): void {
    const media = this.media
    const mediaDuration = media && Number.isFinite(media.duration) && media.duration > 0 ? media.duration : null
    const next: ClockState = {
      playing: media ? !media.paused : false,
      rate: media ? media.playbackRate : this.state.rate,
      muted: media ? media.muted : this.state.muted,
      duration: mediaDuration ?? Math.max(this.durationHint, 0),
      ready: mediaDuration !== null,
      loop: this.state.loop,
    }
    const prev = this.state
    const keys = ['playing', 'rate', 'muted', 'duration', 'ready'] as const
    if (keys.every((key) => prev[key] === next[key])) return
    this.state = next
    this.stateListeners.forEach((listener) => listener())
  }

  private setTime(time: number): void {
    if (time === this.time) return
    this.time = time
    this.timeListeners.forEach((listener) => listener())
  }

  private startFrames(): void {
    if (this.frame !== null) return
    this.frame = this.frames.request(this.onFrame)
  }

  private stopFrames(): void {
    if (this.frame === null) return
    this.frames.cancel(this.frame)
    this.frame = null
  }

  private onFrame = (): void => {
    this.frame = null
    const media = this.media
    if (!media || media.paused) return
    const loop = this.state.loop
    if (loop && this.insideLoop(loop) && media.currentTime >= loop.end_sec) media.currentTime = loop.start_sec
    this.setTime(media.currentTime)
    this.frame = this.frames.request(this.onFrame)
  }
}
