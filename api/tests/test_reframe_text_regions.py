"""Per-region text geometry (Phase 3): clustering, bug classification, and the
per-region conflict test that stops watermark-driven over-letterboxing."""

from reframe_plan import RUNGS, _maybe_text_escalation
from reframe_signals import _segment_text_regions
from text_detect import persistent_text_regions

SRC_W, SRC_H = 1920, 1080


def _tf(t, lines):
    """A scan_video_text frame with per-line boxes."""
    if lines:
        x0 = min(ln[0] for ln in lines)
        x1 = max(ln[2] for ln in lines)
        cov, span = x1 - x0, (x0, x1)
    else:
        cov, span = 0.0, (0.0, 0.0)
    return {"time_sec": t, "coverage": cov, "span": span, "lines": lines}


CAPTION = (0.15, 0.80, 0.85, 0.86)  # wide lower-third
BUG = (0.88, 0.05, 0.97, 0.09)  # small top-right channel bug
CALLOUT = (0.02, 0.40, 0.30, 0.46)  # left-edge callout


# ---------------------------------------------------------------------------
# persistent_text_regions
# ---------------------------------------------------------------------------
def test_legacy_frames_without_lines_return_none():
    frames = [{"time_sec": 0.0, "coverage": 0.5, "span": (0.2, 0.7)}]
    assert persistent_text_regions(frames) is None


def test_lines_cluster_into_one_region_across_frames():
    frames = [_tf(t, [CAPTION]) for t in (0.0, 0.5, 1.0)]
    regions = persistent_text_regions(frames)
    assert len(regions) == 1
    assert regions[0]["kind"] == "candidate"
    assert regions[0]["video_frac"] == 1.0


def test_corner_bug_classified_and_caption_not():
    # Bug present in EVERY frame; caption only in the last two (shot-local).
    frames = [
        _tf(0.0, [BUG]),
        _tf(0.5, [BUG]),
        _tf(1.0, [BUG, CAPTION]),
        _tf(1.5, [BUG, CAPTION]),
    ]
    regions = {r["kind"]: r for r in persistent_text_regions(frames)}
    assert regions["bug"]["box"][0] > 0.8  # the corner box
    assert regions["candidate"]["box"][2] > 0.8  # the wide caption


def test_wide_persistent_caption_is_not_a_bug():
    # Subtitles present through the whole video are still candidates: they fail
    # the area and corner gates even at video_frac 1.0.
    frames = [_tf(t, [CAPTION]) for t in (0.0, 0.5, 1.0, 1.5)]
    (region,) = persistent_text_regions(frames)
    assert region["kind"] == "candidate"


# ---------------------------------------------------------------------------
# _segment_text_regions
# ---------------------------------------------------------------------------
def test_bug_never_reaches_the_segment_band():
    frames = [_tf(t, [BUG]) for t in (0.0, 0.5, 1.0, 1.5)]
    regions = persistent_text_regions(frames)
    cov, span, active = _segment_text_regions(frames, regions)
    assert cov == 0.0 and active == []


def test_candidate_band_is_the_region_not_the_union_with_the_bug():
    # Pre-Phase-3, the per-frame union of bug+caption spanned 0.15→0.97 and the
    # requirement inflated to frame width. Per-region, the band is the caption.
    frames = [_tf(t, [BUG, CAPTION]) for t in (0.0, 0.5, 1.0, 1.5)]
    regions = persistent_text_regions(frames)
    cov, (x0, x1), active = _segment_text_regions(frames, regions)
    assert len(active) == 1
    assert abs(x0 - CAPTION[0]) < 0.02 and abs(x1 - CAPTION[2]) < 0.02


def test_legacy_fallback_uses_union_band():
    frames = [
        {"time_sec": t, "coverage": 0.5, "span": (0.2, 0.7)} for t in (0.0, 0.5, 1.0)
    ]
    cov, span, active = _segment_text_regions(frames, None)
    assert cov == 0.5 and active == []


# ---------------------------------------------------------------------------
# _maybe_text_escalation with regions
# ---------------------------------------------------------------------------
def _regions_of(*boxes):
    return [
        {"box": list(b), "times": [0.0], "video_frac": 0.1, "kind": "candidate"}
        for b in boxes
    ]


def test_escalation_band_is_offending_regions_only():
    # A caption safely behind the subject + a left-edge callout: only the
    # callout conflicts, so the verdict band must be the callout — not the
    # union reaching across the whole frame.
    behind = (0.40, 0.8, 0.60, 0.86)
    regions = [
        {"box": list(behind), "times": [0.0], "video_frac": 0.1, "kind": "candidate"},
        {"box": list(CALLOUT), "times": [0.0], "video_frac": 0.1, "kind": "candidate"},
    ]
    x0 = min(behind[0], CALLOUT[0])
    x1 = max(behind[2], CALLOUT[2])
    pt = _maybe_text_escalation(
        (x1 - x0, (x0, x1)), 0.5, 1, SRC_W, SRC_H, RUNGS, 0.0, 5.0, regions=regions
    )
    assert pt is not None
    band = pt["facts"]["band"]
    assert abs(band[0] - CALLOUT[0]) < 0.02
    assert abs(band[1] - CALLOUT[2]) < 0.02


def test_no_escalation_when_all_regions_behind_subject():
    behind = (0.42, 0.8, 0.58, 0.86)
    regions = _regions_of(behind)
    pt = _maybe_text_escalation(
        (0.16, (0.42, 0.58)), 0.5, 1, SRC_W, SRC_H, RUNGS, 0.0, 5.0, regions=regions
    )
    assert pt is None
