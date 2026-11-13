"""Bind LLM prose to a deterministic engagement report.

The model only ever supplies text and refers to report items by id / key. Every
number in the result is copied from the report or the timeline, and references
the report does not contain are dropped. All functions return new dicts and leave
their inputs untouched. Pure module: no I/O.
"""

from __future__ import annotations

import heapq
from typing import Any

EXPECTED_LIFTS: frozenset[str] = frozenset({"low", "medium", "high"})
_MAX_TITLE_CHARS = 200
_MAX_PROSE_CHARS = 2000
_MAX_DRIVERS = 6
_MAX_ANCHORS = 5
_MAX_INFLUENCE_INPUTS = 8
_MAX_SEGMENT_INPUTS = 5
_INFLUENCE_INPUT_FIELDS = (
    "key",
    "name",
    "kind",
    "delta_pct",
    "avg_during",
    "coverage_sec",
    "coverage_pct",
)


def empty_recommendations() -> dict:
    """A `ReportRecommendations` block with no prose yet."""
    return {"headline": "", "do_more": [], "do_less": [], "segment_fixes": []}


def _text(value: object, limit: int = _MAX_PROSE_CHARS) -> str:
    """Trimmed, length-capped text; anything that is not a string becomes ''."""
    return value.strip()[:limit] if isinstance(value, str) else ""


def _dict_items(value: object) -> list[dict[str, Any]]:
    """The dict entries of a model-supplied list (anything else is ignored)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _driver_names(value: object) -> list[str]:
    """Up to six non-empty driver strings from a model-supplied list."""
    if not isinstance(value, list):
        return []
    names = [_text(entry, _MAX_TITLE_CHARS) for entry in value]
    return [name for name in names if name][:_MAX_DRIVERS]


def apply_explanations(report: dict, items: list[dict]) -> dict:
    """Attach `{id, title, explanation, drivers}` prose to extrema by id.

    Unknown ids are ignored, extrema without an item keep their empty prose, a
    repeated id keeps its first item, and no numeric field is ever taken from
    `items`.
    """
    prose_by_id: dict[str, dict[str, Any]] = {}
    for item in _dict_items(items):
        ident = item.get("id")
        if isinstance(ident, str):
            prose_by_id.setdefault(ident, item)
    extrema: list[dict] = []
    for extremum in report.get("extrema") or []:
        bound = {
            **extremum,
            "window": dict(extremum.get("window") or {}),
            "drivers": list(extremum.get("drivers") or []),
        }
        prose = prose_by_id.get(extremum.get("id"))
        if prose is not None:
            bound["title"] = _text(prose.get("title"), _MAX_TITLE_CHARS)
            bound["explanation"] = _text(prose.get("explanation"))
            bound["drivers"] = _driver_names(prose.get("drivers"))
        extrema.append(bound)
    return {**report, "extrema": extrema}


def _segment_input(stat: dict, segment: dict[str, Any]) -> dict:
    """One segment with its statistics for the recommendation prompt."""
    return {
        "segment_id": stat["segment_id"],
        "title": segment.get("title") or "",
        "synopsis": _text(segment.get("synopsis"), _MAX_TITLE_CHARS * 2),
        "start_sec": segment.get("start_sec"),
        "end_sec": segment.get("end_sec"),
        "avg": stat["avg"],
        "delta_pct": stat["delta_pct"],
        "rank": stat["rank"],
    }


def recommendation_inputs(report: dict, timeline: dict) -> dict:
    """Compact, deterministic facts for the recommendation prompt.

    Keys: `content_title`, `summary`, `duration_sec`, `signal`, `stats`,
    `top_influence` / `bottom_influence` (strongest positive / negative entries
    with enough support, each with its `key`), and `high_segments` /
    `low_segments` (above / below average, each with its `segment_id`).
    """
    supported = [e for e in report.get("influence") or [] if not e["low_support"]]
    top = heapq.nlargest(
        _MAX_INFLUENCE_INPUTS,
        (e for e in supported if e["delta_pct"] > 0),
        key=lambda e: e["delta_pct"],
    )
    bottom = heapq.nsmallest(
        _MAX_INFLUENCE_INPUTS,
        (e for e in supported if e["delta_pct"] < 0),
        key=lambda e: e["delta_pct"],
    )
    segments = {s.get("id"): s for s in timeline.get("segments") or []}
    ranked = sorted(
        (s for s in report.get("segments") or [] if s["segment_id"] in segments),
        key=lambda s: s["rank"],
    )
    high = [s for s in ranked if s["delta_pct"] > 0][:_MAX_SEGMENT_INPUTS]
    low = [s for s in reversed(ranked) if s["delta_pct"] < 0][:_MAX_SEGMENT_INPUTS]
    signal = report.get("signal") or {}
    return {
        "content_title": timeline.get("content_title") or "",
        "summary": _text(timeline.get("summary")),
        "duration_sec": report.get("duration_sec", 0.0),
        "signal": {
            name: signal.get(name)
            for name in ("label", "simulated", "primary_metric", "unit")
        },
        "stats": dict(report.get("stats") or {}),
        "top_influence": [
            {name: e[name] for name in _INFLUENCE_INPUT_FIELDS} for e in top
        ],
        "bottom_influence": [
            {name: e[name] for name in _INFLUENCE_INPUT_FIELDS} for e in bottom
        ],
        "high_segments": [_segment_input(s, segments[s["segment_id"]]) for s in high],
        "low_segments": [_segment_input(s, segments[s["segment_id"]]) for s in low],
    }


def _evidence_key(item: dict[str, Any]) -> str:
    """The influence key an item cites: `key`, `evidence_key` or `evidence.key`."""
    nested = item.get("evidence")
    cited = item.get("key") or item.get("evidence_key")
    if not cited and isinstance(nested, dict):
        cited = nested.get("key")
    return cited.strip() if isinstance(cited, str) else ""


def _evidence(entry: dict) -> dict:
    """`RecommendationEvidence` copied from a report influence entry.

    `anchor_times` are the starts of its longest ranges, in time order.
    """
    longest = heapq.nlargest(
        _MAX_ANCHORS,
        entry.get("ranges") or [],
        key=lambda r: r["end_sec"] - r["start_sec"],
    )
    return {
        "key": entry["key"],
        "name": entry["name"],
        "kind": entry["kind"],
        "delta_pct": entry["delta_pct"],
        "coverage_sec": entry["coverage_sec"],
        "anchor_times": sorted(r["start_sec"] for r in longest),
    }


def _bind_actions(items: object, influence: dict[str, dict]) -> list[dict]:
    """`ReportRecommendation` list; items citing an unknown key are dropped."""
    actions: list[dict] = []
    for item in _dict_items(items):
        title = _text(item.get("title"), _MAX_TITLE_CHARS)
        key = _evidence_key(item)
        if not title or (key and key not in influence):
            continue
        lift = item.get("expected_lift")
        actions.append(
            {
                "title": title,
                "rationale": _text(item.get("rationale")),
                "expected_lift": lift if lift in EXPECTED_LIFTS else "low",
                "evidence": _evidence(influence[key]) if key else None,
            }
        )
    return actions


def _bind_fixes(
    items: object, stats: dict[str, dict], segments: dict[str, dict[str, Any]]
) -> list[dict]:
    """`ReportSegmentFix` list; unknown or repeated segments are dropped."""
    fixes: dict[str, dict] = {}
    for item in _dict_items(items):
        ident = item.get("segment_id")
        prose = {
            name: _text(item.get(name)) for name in ("what_happened", "why_low", "fix")
        }
        if not isinstance(ident, str) or ident in fixes or not any(prose.values()):
            continue
        stat, segment = stats.get(ident), segments.get(ident)
        if stat is None or segment is None:
            continue
        fixes[ident] = {
            "segment_id": ident,
            "start_sec": segment["start_sec"],
            "end_sec": segment["end_sec"],
            "avg": stat["avg"],
            **prose,
        }
    return list(fixes.values())


def apply_recommendations(report: dict, payload: dict, timeline: dict) -> dict:
    """Attach the model's recommendations, with every number taken from our data.

    `payload` is `{headline, do_more[], do_less[], segment_fixes[]}`. A
    `do_more` / `do_less` item is `{title, rationale, expected_lift, key}`; its
    evidence figures come from the report's influence entry for `key`. An item
    citing a key the report does not have is dropped; an item citing no key is
    kept with `evidence: None`. A segment fix is `{segment_id, what_happened,
    why_low, fix}`; its times come from `timeline` and its average from the
    report, and fixes for segments unknown to either are dropped.
    """
    body = payload if isinstance(payload, dict) else {}
    influence = {e["key"]: e for e in report.get("influence") or []}
    stats = {s["segment_id"]: s for s in report.get("segments") or []}
    segments = {s.get("id"): s for s in timeline.get("segments") or []}
    recommendations = {
        "headline": _text(body.get("headline"), _MAX_TITLE_CHARS * 2),
        "do_more": _bind_actions(body.get("do_more"), influence),
        "do_less": _bind_actions(body.get("do_less"), influence),
        "segment_fixes": _bind_fixes(body.get("segment_fixes"), stats, segments),
    }
    return {**report, "recommendations": recommendations}
