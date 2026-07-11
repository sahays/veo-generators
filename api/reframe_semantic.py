"""Whole-video semantic pass — Gemini judges WHAT/WHEN, the CPU owns WHERE.

One video+audio call (gemini flash-lite by default) returns per-shot
CATEGORICAL judgments: content kind, text importance, speaker screen positions.
No coordinates, no coverage floats — video-mode spatial grounding is unreliable
(near-zero on benchmarks), and the retired dense pass (commit 0d57d70) failed
precisely because its coverage numbers forced rungs. Here every number that
touches crop math is CPU-measured; Gemini's labels only SELECT among measured
facts:

- Letterbox needs a two-key lock: a text element Gemini judged essential/
  contextual (semantic key) AND a measured persistent text region from
  text_detect (geometric key). The kept band is always the measured one;
  Gemini's coarse extent is used only when OpenCV is blind (stylized titles),
  quantized to a rung and flagged low-confidence.
- Subject hints are position buckets snapped to MediaPipe tracks downstream.
- The reconciled output is the exact `scenes` dict shape the planner has
  consumed since v2 (`_scene_for` / `_hint_x` / `_match_track`), so a missing
  or failed pass degrades to `scenes=[]` — today's deterministic behavior.

Pure logic, no I/O: the worker calls GeminiService.analyze_video_semantics and
feeds the payload through validate() → reconcile_semantics().
"""

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

SEMANTIC_MODEL = os.getenv("REFRAME_SEMANTIC_MODEL", "gemini-3.1-flash-lite")

# Shot binding: Gemini echoes the cut list it was given; timestamps within this
# tolerance of a CPU shot boundary bind to it. Beyond it the shot is dropped
# (that segment keeps pure deterministic behavior).
SHOT_EDGE_TOL = 0.75
# A payload whose valid shots cover less than this fraction of the duration is
# treated as garbage (fallback to legacy for the whole video).
MIN_COVERAGE = 0.5

CONTENT_KINDS = {
    "talking_head",
    "multi_person_dialogue",
    "screen_share_slide",
    "title_card",
    "poster_static",
    "action",
    "montage",
    "broll_scenery",
}
# Full-frame designed compositions: keep full width when no measured band
# narrows the requirement.
GRAPHIC_KINDS = {"screen_share_slide", "title_card", "poster_static"}
# Coarse extent bucket → (x0, x1) prior, used ONLY to match against measured
# regions (geometry wins) or, for OpenCV-blind essential text, as the
# low-confidence fallback band.
EXTENT_PRIORS = {
    "left_third": (0.0, 0.38),
    "center_third": (0.31, 0.69),
    "right_third": (0.62, 1.0),
    "left_half": (0.0, 0.55),
    "right_half": (0.45, 1.0),
    "full_width": (0.0, 1.0),
    "corner": (0.75, 1.0),
}
_KEEP_IMPORTANCE = {"essential", "contextual"}


def semantic_pass_enabled(record=None) -> bool:
    """REFRAME_SEMANTIC_PASS env gate with an optional per-record override."""
    override = getattr(record, "semantic_pass", None) if record is not None else None
    if override is not None:
        return bool(override)
    return os.getenv("REFRAME_SEMANTIC_PASS", "off").lower() in ("on", "1", "true")


def build_semantic_prompt(
    cuts: List[float], chirp_context: str, duration: float
) -> str:
    """The whole-video question. Cut list + diarization labels are supplied so
    shots and speakers echo OUR boundaries/ids instead of inventing their own."""
    cut_str = ", ".join(f"{c:.2f}s" for c in cuts) if cuts else "(none — one shot)"
    parts = []
    if chirp_context:
        parts.append(chirp_context)
    parts.append(
        "You are the semantic analyst for an automatic video reframing system "
        "that converts this wide video to a vertical/portrait canvas. "
        "Deterministic computer vision supplies all coordinates; YOUR job is "
        "judgment only: what each shot IS, which on-screen text matters, and "
        "who is speaking where.\n\n"
        f"=== SHOTS ===\nThe video is {duration:.1f}s long with hard cuts at: "
        f"{cut_str}\nDescribe each shot between consecutive cuts (and 0/end). "
        "Echo these boundaries — do not invent new ones (merging adjacent "
        "identical shots is fine).\n\n"
        "=== TEXT: IMPORTANCE, NOT READABILITY ===\nFor burned-in text, judge "
        "whether the VIEWER NEEDS it. A title card, subtitle, price, speaker "
        "name, chart label or quote is essential. A watermark, channel bug, "
        "recurring logo, background signage or decorative type is incidental — "
        "even when perfectly readable. Mark elements that persist across many "
        "shots (bugs/watermarks) persistent=true and list them in `watermarks` "
        "too.\n\n"
        "=== SPEAKERS ===\nThe diarization turns above label WHO speaks WHEN. "
        "For each shot, say where each active speaker appears ON SCREEN "
        "(left/center/right) — or offscreen for narrators and voiceover over "
        "footage that does not show the person talking (a static poster with "
        "narration is poster_static + offscreen, NOT a talking head).\n\n"
        "Answer with JSON per the schema. Coarse position buckets only — never "
        "pixel coordinates."
    )
    return "\n\n".join(parts)


def _bind_shot(shot: dict, bounds: List[float]) -> Optional[dict]:
    """Snap a Gemini shot onto CPU cut boundaries (± SHOT_EDGE_TOL)."""

    def snap(t):
        best = min(bounds, key=lambda b: abs(b - t))
        return best if abs(best - t) <= SHOT_EDGE_TOL else t

    start, end = snap(float(shot["start_sec"])), snap(float(shot["end_sec"]))
    if end - start <= 0.05:
        return None
    return {**shot, "start_sec": round(start, 3), "end_sec": round(end, 3)}


def validate(payload: dict, cuts: List[float], duration: float) -> Optional[List[dict]]:
    """Sanity-check the model payload → cleaned, cut-bound shot list.

    Returns None when the payload is unusable (wrong shape / near-zero
    coverage) — the caller falls back to the legacy escalation path. Partially
    valid payloads keep their good shots; uncovered spans simply get no scene
    (`{}` → deterministic behavior for those segments).
    """
    shots = (payload or {}).get("shots")
    if not isinstance(shots, list) or not shots:
        return None
    bounds = sorted({0.0, *(c for c in cuts if 0 < c < duration), duration})
    cleaned: List[dict] = []
    covered = 0.0
    for shot in shots:
        try:
            if shot.get("content_kind") not in CONTENT_KINDS:
                continue
            bound = _bind_shot(shot, bounds)
        except (KeyError, TypeError, ValueError):
            continue
        if not bound:
            continue
        if bound["start_sec"] >= duration or bound["end_sec"] <= 0:
            continue
        if cleaned and bound["start_sec"] < cleaned[-1]["end_sec"] - SHOT_EDGE_TOL:
            continue  # overlapping/garbled — keep the earlier shot
        cleaned.append(bound)
        covered += bound["end_sec"] - bound["start_sec"]
    if not cleaned or covered < MIN_COVERAGE * max(duration, 0.001):
        return None
    return cleaned


def _overlaps(a0, a1, b0, b1) -> bool:
    return min(a1, b1) - max(a0, b0) > 0.0


def _text_keep(shot: dict, regions: Optional[List[dict]]) -> Optional[dict]:
    """Two-key letterbox lock for one shot.

    Semantic key: an essential/contextual, non-watermark text element. Geometric
    key: a measured candidate region active during the shot whose horizontal
    extent overlaps the element's coarse prior. The kept band is the MEASURED
    union; the coarse prior alone is used only when the CPU detector saw
    nothing (stylized titles), flagged low_confidence.

    Measured text that Gemini called incidental (or never mentioned) yields
    None → crop. That asymmetry is deliberate: the CPU band alone letterboxed
    busy backgrounds for months; the semantic key is what was always missing.
    """
    keeps = [
        el
        for el in shot.get("text_elements") or []
        if el.get("importance") in _KEEP_IMPORTANCE
        and el.get("kind") != "watermark_bug"
    ]
    if not keeps:
        return None
    start, end = shot["start_sec"], shot["end_sec"]
    active = [
        r
        for r in regions or []
        if r.get("kind") != "bug" and any(start <= t <= end for t in r.get("times", []))
    ]
    matched: List[dict] = []
    unmatched_priors = []
    for el in keeps:
        prior = EXTENT_PRIORS.get(el.get("extent"), (0.0, 1.0))
        hits = [
            r for r in active if _overlaps(prior[0], prior[1], r["box"][0], r["box"][2])
        ]
        if hits:
            matched.extend(hits)
        else:
            unmatched_priors.append(prior)
    if matched:
        x0 = min(r["box"][0] for r in matched)
        x1 = max(r["box"][2] for r in matched)
        return {"band": [round(x0, 3), round(x1, 3)], "low_confidence": False}
    if unmatched_priors:
        x0 = min(p[0] for p in unmatched_priors)
        x1 = max(p[1] for p in unmatched_priors)
        return {"band": [round(x0, 3), round(x1, 3)], "low_confidence": True}
    return None


_SCENE_TYPE = {
    "talking_head": "dialogue",
    "multi_person_dialogue": "dialogue",
    "action": "action",
    "montage": "action",
}


def reconcile_semantics(
    shots: List[dict],
    text_regions: Optional[List[dict]],
) -> List[dict]:
    """Validated shots → the planner's `scenes` dicts.

    Emits the legacy keys (`start_sec`, `end_sec`, `scene_type`, `layout`,
    `active_subject`) so `_scene_for`/`_hint_x`/`_match_track`/`_keep_both_pair`
    work unmodified, plus the semantic keys (`content_kind`, `text_keep`,
    `speakers`) the Phase-4/5 branches consume. Never emits coverage floats or
    `requires_full_width` — the dense-pass failure must stay impossible.
    """
    scenes = []
    for shot in shots:
        subject = shot.get("key_subject") or {}
        pos = subject.get("position")
        scene = {
            "start_sec": shot["start_sec"],
            "end_sec": shot["end_sec"],
            "content_kind": shot["content_kind"],
            "scene_type": _SCENE_TYPE.get(shot["content_kind"], "general"),
            "layout": (
                "side_by_side"
                if shot["content_kind"] == "multi_person_dialogue"
                else ""
            ),
            "active_subject": pos if pos in ("left", "center", "right") else "",
            "speakers": shot.get("speakers") or [],
            "text_keep": _text_keep(shot, text_regions),
        }
        scenes.append(scene)
    return scenes
