"""Normalise per-window model output and merge windows into one `TimelineDoc`.

Pure functions: no I/O and no service singletons.

Pipeline: the model's raw JSON for one window goes through
`normalize_window_result` (absolute seconds, clamped to the window, malformed
items dropped). `merge_windows` then combines the normalised windows into the
`timeline.json` document. The merge sorts everything by content, so the result
does not depend on the order the windows finished in.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence

from models_insights import TIMELINE_SCHEMA_VERSION
from timeline_windows import Window, nearest_cut

# A timestamp this far outside the window still counts as "inside" when voting
# on the time base, and a point marker this far outside is pulled back in.
_VOTE_SLACK_SEC = 1.0
# Appearances closer together than this are one continuous appearance.
_TOUCH_EPS_SEC = 0.05
# Segment boundaries this close to a detected cut move onto it.
_SEGMENT_SNAP_SEC = 0.75
# Gaps between consecutive segments up to this long are closed.
_SEGMENT_GAP_SEC = 1.0
_NAME_STRIP_CHARS = " .,;:!?\"'()[]{}"
_TEXT_DEFAULTS = {"kind": "dialogue"}


@dataclass(frozen=True)
class _Spec:
    """How one timeline collection is validated, de-duplicated and labelled.

    `required[0]` identifies an item for de-duplication. When `needs_identity`
    is set, items whose identity text is empty are dropped.
    """

    id_prefix: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    unit: str = ""  # name of a 0..1 numeric field, if the collection has one
    unit_default: Optional[float] = None  # None: omit the field when missing
    point: bool = False  # point marker (start only) rather than a range
    needs_identity: bool = True


_SPECS: dict[str, _Spec] = {
    "segments": _Spec(
        "seg", ("title", "synopsis"), ("location",), needs_identity=False
    ),
    "cues": _Spec("cue", ("text", "kind"), ("speaker", "sentiment")),
    "events": _Spec("evt", ("tag",), ("description",), unit="intensity"),
    "emotions": _Spec("emo", ("emotion",), unit="intensity", unit_default=0.5),
    "key_moments": _Spec("km", ("type", "label"), point=True),
    "narrative_beats": _Spec("nb", ("beat",), ("label",)),
}
_COUNTED = (*_SPECS, "entities", "cuts")


# ── Small value helpers ──────────────────────────────────────────────


def _num(value: Any) -> Optional[float]:
    """Parse a finite number; booleans, NaN, infinities and junk give None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _dicts(value: Any) -> list[dict]:
    """The dict members of `value` when it is a list, else an empty list."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _fit_span(item: dict, shift: float, low: float, high: float) -> Optional[dict]:
    """Shift, clamp to `[low, high]` and round a range; None if it is empty."""
    start, end = _num(item.get("start_sec")), _num(item.get("end_sec"))
    if start is None or end is None:
        return None
    start = round(min(max(start + shift, low), high), 2)
    end = round(min(max(end + shift, low), high), 2)
    if end <= start:
        return None
    return {"start_sec": start, "end_sec": end}


def _fit_point(item: dict, shift: float, low: float, high: float) -> Optional[dict]:
    """Shift and clamp a point marker; None if it lies well outside the range."""
    start = _num(item.get("start_sec"))
    if start is None:
        return None
    start += shift
    if start < low - _VOTE_SLACK_SEC or start > high + _VOTE_SLACK_SEC:
        return None
    return {"start_sec": round(min(max(start, low), high), 2)}


def _fit(
    item: dict, spec: _Spec, shift: float, low: float, high: float
) -> Optional[dict]:
    fit = _fit_point if spec.point else _fit_span
    return fit(item, shift, low, high)


# ── Per-window normalisation ─────────────────────────────────────────


def _raw_timestamps(data: dict) -> Iterator[float]:
    """Every numeric timestamp the model returned for one window."""
    spans = [item for name in _SPECS for item in _dicts(data.get(name))]
    for entity in _dicts(data.get("entities")):
        spans.extend(_dicts(entity.get("appearances")))
    for span in spans:
        for key in ("start_sec", "end_sec"):
            value = _num(span.get(key))
            if value is not None:
                yield value


def _is_window_relative(data: dict, window: Window) -> bool:
    """Majority vote on the time base of one window's raw result.

    Each timestamp votes for every reading (absolute, window-relative) that
    places it inside the window. Relative wins only with a strict majority, so
    a tie, including the case where every timestamp fits both readings, keeps
    the timestamps as absolute.
    """
    absolute = relative = 0
    low, high = window.start_sec - _VOTE_SLACK_SEC, window.end_sec + _VOTE_SLACK_SEC
    for value in _raw_timestamps(data):
        absolute += low <= value <= high
        relative += low <= value + window.start_sec <= high
    return relative > absolute


def _clean_fields(item: dict, spec: _Spec) -> Optional[dict]:
    """Keep the collection's known fields; None when the identity is missing."""
    fields: dict[str, Any] = {}
    for name in spec.required:
        fields[name] = _text(item.get(name)) or _TEXT_DEFAULTS.get(name, "")
    if spec.needs_identity and not fields[spec.required[0]]:
        return None
    for name in spec.optional:
        value = _text(item.get(name))
        if value:
            fields[name] = value
    if spec.unit:
        unit = _num(item.get(spec.unit))
        unit = spec.unit_default if unit is None else unit
        if unit is not None:
            fields[spec.unit] = round(min(1.0, max(0.0, unit)), 3)
    return fields


def _clean_items(
    items: list[dict], spec: _Spec, shift: float, window: Window
) -> list[dict]:
    cleaned = []
    for item in items:
        span = _fit(item, spec, shift, window.start_sec, window.end_sec)
        fields = _clean_fields(item, spec) if span else None
        if span and fields is not None:
            cleaned.append({**span, **fields})
    return cleaned


def _clean_entities(items: list[dict], shift: float, window: Window) -> list[dict]:
    cleaned = []
    for item in items:
        name = _text(item.get("name"))
        spans = [
            _fit_span(a, shift, window.start_sec, window.end_sec)
            for a in _dicts(item.get("appearances"))
        ]
        appearances = [s for s in spans if s]
        if not name or not appearances:
            continue
        entity = {
            "name": name,
            "kind": _text(item.get("kind")) or "object",
            "appearances": appearances,
        }
        description = _text(item.get("description"))
        if description:
            entity["description"] = description
        cleaned.append(entity)
    return cleaned


def _window_stamp(window: Window) -> dict:
    return {
        "index": window.index,
        "start_sec": window.start_sec,
        "end_sec": window.end_sec,
    }


def normalize_window_result(raw: dict, window: Window) -> dict:
    """Turn one window's raw model JSON into a clean, absolute-time result.

    The model may return timestamps measured from the start of the window or
    from the start of the full video; `_is_window_relative` decides which, and
    relative timestamps are shifted by the window start. Ranges are then
    clamped to the window, inverted or empty ranges and items without their
    identifying text are dropped, and times are rounded to 2 decimals.

    The result carries the window it belongs to (`window`) and the time base
    that was detected (`time_base`, for diagnostics).
    """
    data = raw if isinstance(raw, dict) else {}
    relative = _is_window_relative(data, window)
    shift = window.start_sec if relative else 0.0
    result: dict[str, Any] = {
        "window": _window_stamp(window),
        "time_base": "relative" if relative else "absolute",
        "summary": _text(data.get("summary")),
        "content_title": _text(data.get("content_title")),
    }
    for name, spec in _SPECS.items():
        result[name] = _clean_items(_dicts(data.get(name)), spec, shift, window)
    result["entities"] = _clean_entities(_dicts(data.get("entities")), shift, window)
    return result


def _window_order(result: dict) -> tuple[float, float, str]:
    """Sort key placing window results in video order, whatever their arrival."""
    window = result.get("window") or {}
    start = _num(window.get("start_sec")) or 0.0
    index = _num(window.get("index")) or 0.0
    return (start, index, str(result.get("summary", "")))


def combine_window_parts(parts: Sequence[dict], window: Window) -> dict:
    """Join the normalised results of a split window back into one result.

    Used when a window had to be analysed in halves. The combined result is
    what gets checkpointed and merged under the parent window.
    """
    ordered = sorted(parts, key=_window_order)
    combined: dict[str, Any] = {
        "window": _window_stamp(window),
        "time_base": "absolute",
        "summary": " ".join(p["summary"] for p in ordered if p.get("summary")),
        "content_title": next(
            (p["content_title"] for p in ordered if p.get("content_title")), ""
        ),
    }
    for name in (*_SPECS, "entities"):
        combined[name] = [item for p in ordered for item in p.get(name) or []]
    return combined


# ── Cross-window merge ───────────────────────────────────────────────


def _merge_collection(
    ordered: Sequence[dict], name: str, spec: _Spec, duration: float
) -> list[dict]:
    """Clamp to the video, sort by time then content, drop duplicate items.

    Two items are duplicates when they share start, end and identity text.
    Sorting on the full canonical item first makes the survivor of a duplicate
    group independent of input order.
    """
    keyed = []
    for result in ordered:
        for item in _dicts(result.get(name)):
            span = _fit(item, spec, 0.0, 0.0, duration)
            if span is None:
                continue
            fitted = {**item, **span}
            identity = (
                span["start_sec"],
                span.get("end_sec", span["start_sec"]),
                str(fitted.get(spec.required[0], "")).casefold(),
            )
            keyed.append((identity, json.dumps(fitted, sort_keys=True), fitted))
    keyed.sort(key=lambda entry: entry[:2])
    merged: list[dict] = []
    previous: Optional[tuple] = None
    for identity, _, fitted in keyed:
        if identity != previous:
            merged.append(fitted)
            previous = identity
    return merged


def _tidy_segments(
    segments: list[dict], cuts: Sequence[float], duration: float
) -> list[dict]:
    """Make time-sorted segments a clean partition of the covered footage.

    Boundaries move onto a detected cut when one is very close. A segment that
    runs into the next one is cut short at the next start, small gaps are
    closed, and a segment that is empty or does not start after the previous
    one is dropped. Larger gaps are kept: they mark footage the model did not
    describe.
    """
    tidy: list[dict] = []
    for segment in segments:
        start = nearest_cut(cuts, segment["start_sec"], _SEGMENT_SNAP_SEC)
        end = nearest_cut(cuts, segment["end_sec"], _SEGMENT_SNAP_SEC)
        start = segment["start_sec"] if start is None else start
        end = segment["end_sec"] if end is None else end
        if not tidy and start <= _SEGMENT_GAP_SEC:
            start = 0.0
        if tidy and start <= tidy[-1]["start_sec"]:
            continue
        if tidy and (
            tidy[-1]["end_sec"] > start
            or start - tidy[-1]["end_sec"] <= _SEGMENT_GAP_SEC
        ):
            tidy[-1]["end_sec"] = start
        if end > start:
            tidy.append({**segment, "start_sec": start, "end_sec": end})
    if tidy and duration - tidy[-1]["end_sec"] <= _SEGMENT_GAP_SEC:
        tidy[-1]["end_sec"] = duration
    return tidy


def _entity_key(entity: dict) -> tuple[str, str]:
    """`(normalised name, kind)`: the identity of an entity across windows."""
    name = unicodedata.normalize("NFKC", str(entity.get("name", ""))).casefold()
    return (" ".join(name.split()).strip(_NAME_STRIP_CHARS), str(entity.get("kind")))


def _merge_spans(spans: Sequence[dict], duration: float) -> list[dict]:
    """Clamp, sort and fuse overlapping or touching appearances."""
    fitted = [_fit_span(span, 0.0, 0.0, duration) for span in spans]
    ranges = sorted((s["start_sec"], s["end_sec"]) for s in fitted if s)
    fused: list[list[float]] = []
    for start, end in ranges:
        if fused and start <= fused[-1][1] + _TOUCH_EPS_SEC:
            fused[-1][1] = max(fused[-1][1], end)
        else:
            fused.append([start, end])
    return [{"start_sec": a, "end_sec": b} for a, b in fused]


def _build_entity(members: list[dict], duration: float) -> Optional[dict]:
    """Fuse every mention of one entity; None if it never appears on screen."""
    spans = [span for m in members for span in _dicts(m.get("appearances"))]
    appearances = _merge_spans(spans, duration)
    if not appearances:
        return None
    # Most frequent spelling; a tie goes to the one seen first in video order.
    names = Counter(str(m["name"]) for m in members)
    descriptions = [str(m["description"]) for m in members if m.get("description")]
    entity: dict[str, Any] = {
        "name": max(names, key=lambda n: names[n]),
        "kind": str(members[0].get("kind")),
        "appearances": appearances,
        "screen_time_sec": round(
            sum(a["end_sec"] - a["start_sec"] for a in appearances), 2
        ),
    }
    if descriptions:
        entity["description"] = max(descriptions, key=lambda d: (len(d), d))
    return entity


def _merge_entities(ordered: Sequence[dict], duration: float) -> list[dict]:
    """Group entities by `(normalised name, kind)` and rank by screen time."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for result in ordered:
        for entity in _dicts(result.get("entities")):
            key = _entity_key(entity)
            if key[0]:
                groups.setdefault(key, []).append(entity)
    built = [(key, _build_entity(members, duration)) for key, members in groups.items()]
    ranked = sorted(
        ((key, entity) for key, entity in built if entity),
        key=lambda pair: (
            -pair[1]["screen_time_sec"],
            pair[1]["appearances"][0]["start_sec"],
            pair[0],
        ),
    )
    return [entity for _, entity in ranked]


def _with_ids(items: Sequence[dict], prefix: str) -> list[dict]:
    return [{"id": f"{prefix}-{n}", **item} for n, item in enumerate(items, start=1)]


def merge_windows(results: list[dict], duration_sec: float, cuts: list[float]) -> dict:
    """Merge normalised window results into the `TimelineDoc` for `timeline.json`.

    Independent of the order of `results`. Every time is clamped to
    `[0, duration_sec]` and rounded to 2 decimals; every list is sorted by
    start time (entities by descending screen time) and its items get stable
    1-based ids (`seg-1`, `cue-1`, `ent-1`, `evt-1`, `emo-1`, `km-1`, `nb-1`).
    Entities are matched across windows by normalised name and kind, and their
    touching appearances are fused before `screen_time_sec` is summed.
    """
    duration = round(max(0.0, float(duration_sec)), 2)
    ordered = sorted(_dicts(results), key=_window_order)
    clean_cuts = sorted({round(float(c), 2) for c in cuts if 0 < c < duration})
    merged = {
        name: _merge_collection(ordered, name, spec, duration)
        for name, spec in _SPECS.items()
    }
    merged["segments"] = _tidy_segments(merged["segments"], clean_cuts, duration)
    lists = {name: _with_ids(merged[name], _SPECS[name].id_prefix) for name in merged}
    lists["entities"] = _with_ids(_merge_entities(ordered, duration), "ent")
    summaries = [str(r["summary"]) for r in ordered if r.get("summary")]
    titles = [str(r["content_title"]) for r in ordered if r.get("content_title")]
    return {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "duration_sec": duration,
        "summary": " ".join(summaries),
        "content_title": titles[0] if titles else "",
        "cuts": clean_cuts,
        "segments": lists["segments"],
        "cues": lists["cues"],
        "entities": lists["entities"],
        "events": lists["events"],
        "emotions": lists["emotions"],
        "key_moments": lists["key_moments"],
        "narrative_beats": lists["narrative_beats"],
    }


def timeline_counts(timeline: dict) -> dict[str, int]:
    """Item count per timeline collection, for the Firestore record summary."""
    return {name: len(timeline.get(name) or []) for name in _COUNTED}
