"""Escalation batching — decide WHEN the planner calls Gemini, and bundle it.

Planning stays deterministic and authoritative: `reframe_plan` resolves every
segment it can on facts alone, and at each *borderline* judgment (the fuzzy
nested-if branches — text-vs-background, which-subject, active-speaker,
keep-both, split, no-subject) it emits an **escalation point** instead of
silently guessing. Each point carries its deterministic *fallback* decision, so
the plan is fully renderable even if Gemini is never called or rate-limits out.

This module turns that flat list of points into a small number of batched
`gemini-3.5-flash` requests. Per-segment calls would hammer the API and trip
429s; instead we:

  1. **cluster** points that ask the *same question about the same entities*
     (the same two faces across adjacent segments → one question),
  2. **chunk** the clusters into few requests (≤ MAX_POINTS_PER_CALL each), and
  3. **budget** the whole video to MAX_CALLS_PER_VIDEO requests — beyond that,
     keep the highest-impact (longest-duration) ambiguities and let the rest
     fall back deterministically, logging exactly what was dropped.

Pass 2 (the actual model call) consumes `plan_batches(...)["batches"]` and runs
them sequentially with exponential backoff. This module makes NO network calls.
"""

from typing import List, Optional

# The decision model for every escalated call (multimodal: facts + thumbnails).
DECISION_MODEL = "gemini-3.5-flash"

# Batching guard. Calls run SEQUENTIALLY (one at a time, with backoff) — multiple
# calls per video are fine, parallel fan-out is what trips 429s. Each request
# carries at most MAX_POINTS_PER_CALL clusters (and their thumbnails) to keep a
# single request small and reliable. MAX_CALLS_PER_VIDEO is a generous runaway
# backstop, not a normal limit: a typical video clusters to 1–3 calls; only a
# pathological one approaches the cap, beyond which lowest-impact ambiguities
# fall back deterministically (logged, never silent).
# Each cluster now sends ~3 annotated frames, so keep points-per-call modest to
# bound images per request and keep image↔key association reliable.
MAX_POINTS_PER_CALL = 5
MAX_CALLS_PER_VIDEO = 30
MAX_THUMBS_PER_CLUSTER = 3  # representative frames a clustered question sends

# Known escalation kinds (one per fuzzy decision point in reframe_plan).
KINDS = (
    "text_presence",  # #1 wide band: meaningful side text/graphics, or background?
    "subject_choice",  # #3 which of several comparable faces is THE subject?
    "active_speaker",  # #4 who is talking when mouth-variance is inconclusive?
    "keep_both",  # #5 two important people, or one subject + a bystander?
    "split",  # #6 genuine static two-person dialogue worth stacking?
    "no_subject",  # #7 nothing detected — what's the subject (b-roll/graphics)?
    "person_widen",  # #8 borderline wide body — real reason to widen?
)


def make_point(
    kind: str,
    key: str,
    question: str,
    facts: dict,
    fallback: dict,
    start: float,
    end: float,
    thumb_sec: Optional[float] = None,
) -> dict:
    """One borderline decision the planner wants Gemini to settle.

    `key` is the clustering signature: points sharing a key ask the same
    question about the same entities and collapse into a single call. `fallback`
    is the deterministic decision already chosen, applied verbatim if this point
    is never sent (budget drop, Gemini error/skip). `thumb_sec` defaults to the
    segment midpoint — the representative frame to attach.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown escalation kind: {kind!r}")
    return {
        "kind": kind,
        "key": key,
        "question": question,
        "facts": facts,
        "fallback": fallback,
        "start": float(start),
        "end": float(end),
        "thumb_sec": float(thumb_sec if thumb_sec is not None else (start + end) / 2),
    }


def cluster_escalations(points: List[dict]) -> List[dict]:
    """Merge points with the same `key` into one question (first-seen order).

    The same ambiguity recurs across adjacent segments (same faces, same caption
    band); asking once and applying the verdict to all covered segments is what
    keeps the call count low. A cluster's `impact` is the total duration it
    covers — used to prioritize under the call budget.
    """
    order: List[str] = []
    groups: dict = {}
    for p in points:
        k = p["key"]
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(p)
    clusters = []
    for k in order:
        ps = groups[k]
        first = ps[0]
        thumbs: List[float] = []
        for p in ps:
            if p["thumb_sec"] not in thumbs:
                thumbs.append(p["thumb_sec"])
        clusters.append(
            {
                "kind": first["kind"],
                "key": k,
                "question": first["question"],
                "facts": first["facts"],
                "fallback": first["fallback"],
                "thumb_secs": thumbs[:MAX_THUMBS_PER_CLUSTER],
                "starts": [p["start"] for p in ps],
                "start": min(p["start"] for p in ps),
                "end": max(p["end"] for p in ps),
                "count": len(ps),
                "impact": round(sum(p["end"] - p["start"] for p in ps), 3),
            }
        )
    return clusters


def plan_batches(
    points: List[dict],
    max_points: int = MAX_POINTS_PER_CALL,
    max_calls: int = MAX_CALLS_PER_VIDEO,
) -> dict:
    """Cluster, budget, and chunk escalation points into Gemini requests.

    Returns ``{batches, dropped, n_points, n_clusters, n_calls}``:
      - ``batches`` — list of request payloads, each a list of ≤ ``max_points``
        clusters (and ≤ that many thumbnails). Run sequentially with backoff.
      - ``dropped`` — clusters beyond the ``max_points × max_calls`` budget,
        lowest-impact first; their segments keep the deterministic fallback.

    Prioritization preserves time order within the kept set (so a batch reads
    left-to-right through the video) while dropping by lowest impact.
    """
    clusters = cluster_escalations(points)
    cap = max(0, max_points * max_calls)
    dropped: List[dict] = []
    if len(clusters) > cap:
        ranked = sorted(clusters, key=lambda c: c["impact"], reverse=True)
        keep_ids = {id(c) for c in ranked[:cap]}
        dropped = [c for c in clusters if id(c) not in keep_ids]
        clusters = [c for c in clusters if id(c) in keep_ids]
    batches = [
        clusters[i : i + max_points] for i in range(0, len(clusters), max_points)
    ]
    return {
        "batches": batches,
        "dropped": dropped,
        "n_points": len(points),
        "n_clusters": len(clusters) + len(dropped),
        "n_calls": len(batches),
    }


def summarize(plan: dict) -> str:
    """One-line log of the batching outcome — never hide a budget drop."""
    msg = (
        f"escalation: {plan['n_points']} points → {plan['n_clusters']} clusters "
        f"→ {plan['n_calls']} {DECISION_MODEL} call(s)"
    )
    if plan["dropped"]:
        secs = round(sum(c["impact"] for c in plan["dropped"]), 1)
        msg += (
            f"; DROPPED {len(plan['dropped'])} low-impact cluster(s) "
            f"({secs}s) → deterministic fallback (over budget)"
        )
    return msg
