import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { TimelineItemRef } from '@/types/timeline/model'
import { parseTimeParam, toTimeParam } from '@/types/timeline/timeFormat'
import type { TimelineKit } from './timelineContext'

const TIME_PARAM = 't'
const SELECTION_PARAM = 'sel'
const WRITE_DELAY_MS = 300

/** Apply `?t=` and `?sel=` from a link: select the item, seek, and bring the time into view. */
function restoreFromUrl(params: URLSearchParams, kit: TimelineKit, items: ReadonlyMap<string, TimelineItemRef>): void {
  const item = items.get(params.get(SELECTION_PARAM) ?? '')
  if (item) kit.store.getState().select({ kind: item.kind, id: item.id, label: item.label, range: item.range })
  const time = parseTimeParam(params.get(TIME_PARAM)) ?? item?.range.start_sec ?? null
  if (time === null) return
  kit.clock.seek(time)
  kit.viewport.reveal(time)
}

/** Query string for the current moment: `t` in seconds, `sel` when an item is selected. */
function writeToParams(prev: URLSearchParams, kit: TimelineKit): URLSearchParams {
  const next = new URLSearchParams(prev)
  const selectionId = kit.store.getState().selection?.id
  const time = toTimeParam(kit.clock.getTime())
  // A fresh page at the start with nothing selected keeps a clean URL.
  if (time === '0' && !selectionId) next.delete(TIME_PARAM)
  else next.set(TIME_PARAM, time)
  if (selectionId) next.set(SELECTION_PARAM, selectionId)
  else next.delete(SELECTION_PARAM)
  return next
}

/**
 * Keeps the moment in the URL (`?t=12.3&sel=seg-2`) so a copied link reopens
 * at the same time with the same item selected. The URL is read once on
 * mount and written (history `replace`, debounced) when playback pauses,
 * after a seek while paused, and when the selection changes. It is never
 * written during playback.
 */
export function useUrlTimeSync(kit: TimelineKit, items: ReadonlyMap<string, TimelineItemRef>): void {
  const [params, setParams] = useSearchParams()
  const latest = useRef({ params, setParams })
  latest.current = { params, setParams }
  const restored = useRef(false)

  useEffect(() => {
    if (restored.current) return
    restored.current = true
    restoreFromUrl(latest.current.params, kit, items)
  }, [kit, items])

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const schedule = (): void => {
      clearTimeout(timer)
      timer = setTimeout(() => {
        latest.current.setParams((prev) => writeToParams(prev, kit), { replace: true })
      }, WRITE_DELAY_MS)
    }
    const whenPaused = (): void => {
      if (!kit.clock.getState().playing) schedule()
    }
    const unsubscribers = [
      kit.clock.subscribeState(whenPaused),
      kit.clock.subscribeTime(whenPaused),
      kit.store.subscribe((state, prev) => state.selection !== prev.selection && schedule()),
    ]
    return () => {
      clearTimeout(timer)
      unsubscribers.forEach((unsubscribe) => unsubscribe())
    }
  }, [kit])
}
