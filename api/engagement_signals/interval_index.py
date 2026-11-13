"""Static interval index and compact timeline context slices.

`IntervalIndex` answers "what is on at t" and "what overlaps [a, b)" in
O(log n + k log n) for k results, whatever the interval lengths: intervals are
sorted by start and a max-end tree prunes every subtree that ends too early.
`TimelineIndex` holds one index per timeline lane so many windows can be sliced
without rescanning the timeline. Pure module: no I/O.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_MAX_LANE_ITEMS = 24
_MAX_ENTITIES = 30
_MAX_TEXT_CHARS = 240
_SEGMENT_FIELDS = ("id", "start_sec", "end_sec", "title", "synopsis", "location")
_CUE_FIELDS = ("start_sec", "end_sec", "kind", "speaker", "text", "sentiment")
_EVENT_FIELDS = ("start_sec", "end_sec", "tag", "description", "intensity")
_EMOTION_FIELDS = ("start_sec", "end_sec", "emotion", "intensity")
_MOMENT_FIELDS = ("start_sec", "type", "label")


def item_span(item: dict[str, Any]) -> tuple[float, float]:
    """`(start_sec, end_sec)` of a timeline item; no `end_sec` means an instant."""
    start = float(item.get("start_sec", 0.0))
    return start, float(item.get("end_sec", start))


class IntervalIndex(Generic[T]):
    """Immutable index over items that each occupy a time span.

    Build it from timeline items (dicts with `start_sec` / `end_sec`), from any
    items plus a `span` function, or from `(start, end, payload)` triples with
    `from_spans`. Spans are half-open `[start, end)`; one with `end <= start` is
    an instant that occupies exactly its start time.
    """

    def __init__(
        self, items: Iterable[T], span: Callable[[T], tuple[float, float]] = item_span
    ) -> None:
        self._load([(*span(item), item) for item in items])

    @classmethod
    def from_spans(cls, spans: Iterable[tuple[float, float, T]]) -> IntervalIndex[T]:
        """Index `(start_sec, end_sec, payload)` triples; queries return payloads."""
        index: IntervalIndex[T] = cls([])
        index._load(list(spans))
        return index

    def _load(self, spans: list[tuple[float, float, T]]) -> None:
        """Sort the spans by start and build the max-end tree over them."""
        ordered = sorted(spans, key=lambda span: (span[0], span[1]))
        self._starts = [start for start, _, _ in ordered]
        self._ends = [max(start, end) for start, end, _ in ordered]
        self._items = [item for _, _, item in ordered]
        size = 1
        while size < len(ordered):
            size *= 2
        self._size = size
        self._tree = [-math.inf] * (2 * size)
        self._tree[size : size + len(ordered)] = self._ends
        for node in range(size - 1, 0, -1):
            self._tree[node] = max(self._tree[2 * node], self._tree[2 * node + 1])

    def __len__(self) -> int:
        return len(self._items)

    def _ending_from(self, floor: float, upto: int) -> list[int]:
        """Positions below `upto` whose end is at least `floor`, in start order."""
        found: list[int] = []
        stack = [(1, 0, self._size)]
        while stack:
            node, low, high = stack.pop()
            if low >= upto or self._tree[node] < floor:
                continue
            if high - low == 1:
                found.append(low)
                continue
            mid = (low + high) // 2
            stack.append((2 * node + 1, mid, high))
            stack.append((2 * node, low, mid))
        return found

    def _live(self, position: int, time_sec: float) -> bool:
        """True if the span at `position` still runs after `time_sec` (or is an instant)."""
        end = self._ends[position]
        return end > time_sec or end == self._starts[position]

    def at(self, time_sec: float) -> list[T]:
        """Items whose span contains `time_sec` (`start <= t < end`), in start order."""
        upto = bisect_right(self._starts, time_sec)
        hits = self._ending_from(time_sec, upto)
        return [self._items[i] for i in hits if self._live(i, time_sec)]

    def overlapping(self, start_sec: float, end_sec: float) -> list[T]:
        """Items sharing time with `[start_sec, end_sec)`, in start order.

        An empty query window (`end <= start`) is treated as the instant `start`.
        """
        if end_sec <= start_sec:
            return self.at(start_sec)
        upto = bisect_left(self._starts, end_sec)
        hits = self._ending_from(start_sec, upto)
        return [self._items[i] for i in hits if self._live(i, start_sec)]


def _compact(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Keep the listed non-empty fields, truncating long text."""
    kept: dict[str, Any] = {}
    for name in fields:
        value = item.get(name)
        if value is None or value == "":
            continue
        long_text = isinstance(value, str) and len(value) > _MAX_TEXT_CHARS
        kept[name] = value[: _MAX_TEXT_CHARS - 1] + "…" if long_text else value
    return kept


def _thin(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep at most `limit` items, evenly spread across the list."""
    step = -(-len(items) // limit) if len(items) > limit else 1
    return items[::step]


class TimelineIndex:
    """Interval indexes for every lane of a `TimelineDoc`, built once."""

    def __init__(self, timeline: dict[str, Any]) -> None:
        self.segments = IntervalIndex(timeline.get("segments") or [])
        self._lanes: tuple[
            tuple[str, IntervalIndex[dict[str, Any]], tuple[str, ...]], ...
        ] = (
            ("segments", self.segments, _SEGMENT_FIELDS),
            ("cues", IntervalIndex(timeline.get("cues") or []), _CUE_FIELDS),
            ("events", IntervalIndex(timeline.get("events") or []), _EVENT_FIELDS),
            (
                "emotions",
                IntervalIndex(timeline.get("emotions") or []),
                _EMOTION_FIELDS,
            ),
            (
                "key_moments",
                IntervalIndex(timeline.get("key_moments") or []),
                _MOMENT_FIELDS,
            ),
        )
        self._presence: IntervalIndex[dict[str, Any]] = IntervalIndex.from_spans(
            (float(span["start_sec"]), float(span["end_sec"]), entity)
            for entity in timeline.get("entities") or []
            for span in entity.get("appearances") or []
        )

    def segment_at(self, time_sec: float) -> dict[str, Any] | None:
        """The segment containing `time_sec`, or None between segments."""
        hits = self.segments.at(time_sec)
        return hits[0] if hits else None

    def entities_present(
        self, start_sec: float, end_sec: float
    ) -> list[dict[str, Any]]:
        """Distinct entities on screen during the window, by first appearance."""
        present: dict[int, dict[str, Any]] = {}
        for entity in self._presence.overlapping(start_sec, end_sec):
            present.setdefault(id(entity), entity)
        return list(present.values())

    def slice(self, start_sec: float, end_sec: float) -> dict[str, Any]:
        """Compact view of what happens in `[start_sec, end_sec)` for an LLM prompt."""
        view: dict[str, Any] = {
            "start_sec": round(start_sec, 2),
            "end_sec": round(end_sec, 2),
        }
        for name, index, fields in self._lanes:
            hits = _thin(index.overlapping(start_sec, end_sec), _MAX_LANE_ITEMS)
            view[name] = [_compact(item, fields) for item in hits]
        present = self.entities_present(start_sec, end_sec)[:_MAX_ENTITIES]
        view["entities"] = [_compact(e, ("name", "kind")) for e in present]
        return view


def context_slice(
    timeline: dict[str, Any], start_sec: float, end_sec: float
) -> dict[str, Any]:
    """Compact subset of the timeline inside a window.

    Returns `start_sec`, `end_sec`, `segments` (id, times, title, synopsis),
    `cues`, `entities` (name and kind of those present), `events`, `emotions`
    and `key_moments`. For several windows over one timeline, build a
    `TimelineIndex` once and call `slice` on it instead.
    """
    return TimelineIndex(timeline).slice(start_sec, end_sec)
