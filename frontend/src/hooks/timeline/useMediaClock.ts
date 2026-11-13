import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { MediaClock, type ClockState } from '@/store/timeline/mediaClock'

/**
 * Creates the media clock for one workspace. Pass `clock.attach` as the `ref`
 * of the `<video>` element; React calls it with null on unmount, which
 * releases the element.
 *
 * The current time is deliberately not returned: reading it here would
 * re-render the caller on every frame. Components that show time subscribe
 * with `useClockTime` / `useClockValue`; the playhead subscribes imperatively
 * with `clock.subscribeTime`.
 */
export function useMediaClock(durationHint: number): MediaClock {
  const [clock] = useState(() => new MediaClock(durationHint))
  useEffect(() => {
    clock.setDurationHint(durationHint)
  }, [clock, durationHint])
  return clock
}

/** Play state, rate, duration and loop. Does not change while time advances. */
export function useClockState(clock: MediaClock): ClockState {
  return useSyncExternalStore(clock.subscribeState, clock.getState, clock.getState)
}

/**
 * Current time rounded down to `stepSec`. The component re-renders only when
 * the rounded value changes, e.g. ten times a second for the default step.
 */
export function useClockTime(clock: MediaClock, stepSec = 0.1): number {
  const getSnapshot = useCallback(
    () => Math.floor(clock.getTime() / stepSec + 1e-6) * stepSec,
    [clock, stepSec],
  )
  return useSyncExternalStore(clock.subscribeTime, getSnapshot, getSnapshot)
}

interface CachedValue<T> {
  compute: (timeSec: number) => T
  key: unknown
  value: T
}

/**
 * A value derived from the current time, e.g. "the active cue". `compute`
 * runs on every clock tick and must be cheap (an index lookup); the component
 * re-renders only when `keyOf(value)` changes. Pass stable callbacks
 * (`useCallback`), otherwise the cache is rebuilt each render.
 */
export function useClockValue<T>(
  clock: MediaClock,
  compute: (timeSec: number) => T,
  keyOf: (value: T) => unknown,
): T {
  const cache = useRef<CachedValue<T> | null>(null)
  const getSnapshot = useCallback((): T => {
    const value = compute(clock.getTime())
    const key = keyOf(value)
    const hit = cache.current
    if (hit && hit.compute === compute && hit.key === key) return hit.value
    cache.current = { compute, key, value }
    return value
  }, [clock, compute, keyOf])
  return useSyncExternalStore(clock.subscribeTime, getSnapshot, getSnapshot)
}
