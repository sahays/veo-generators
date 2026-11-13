/**
 * Binary search primitives shared by every timeline lookup.
 * Nothing in the timeline kit scans a collection linearly to answer a
 * "what is at time t" question; it goes through these.
 */

/**
 * First index `i` in `[0, length)` for which `isBefore(i)` is false.
 * `isBefore` must be true for a prefix of the range and false for the rest.
 */
export function partitionPoint(length: number, isBefore: (index: number) => boolean): number {
  let lo = 0
  let hi = length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (isBefore(mid)) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** First index whose value is `>= x` in an ascending array (`length` when none). */
export function lowerBound(sorted: ArrayLike<number>, x: number): number {
  return partitionPoint(sorted.length, (i) => sorted[i] < x)
}

/** First index whose value is `> x` in an ascending array (`length` when none). */
export function upperBound(sorted: ArrayLike<number>, x: number): number {
  return partitionPoint(sorted.length, (i) => sorted[i] <= x)
}
