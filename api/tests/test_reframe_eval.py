"""Unit tests for the reference-free reframe eval (api/reframe_eval.py).

Pure geometry/stats over synthetic plans + detections — no cv2/ffmpeg, runs on
the host venv. SRC is 1920x1080 throughout (landscape → 9:16 canvas).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import crop_geometry
from reframe_eval import evaluate, _crop_window, _must_keep_width

SRC_W, SRC_H = 1920, 1080


def _tr(tid, x, w=0.1, mouth=None):
    t = {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": 0.9}
    if mouth is not None:
        t["mouth"] = mouth
    return t


def _seg(start, end, ar, tid, x, trace=None):
    seg = {
        "start": start,
        "end": end,
        "inner_ar": ar,
        "crops": [{"track_id": tid, "keypoints": [(start, x, 0.5), (end, x, 0.5)]}],
        "reason": f"{ar[0]}:{ar[1]}",
    }
    if trace is not None:
        seg["trace"] = trace
    return seg


def _frames(rows):
    """rows: list of (t, [track,...]) → tracked_frames."""
    return [{"time_sec": t, "tracks": tracks} for t, tracks in rows]


# ---------------------------------------------------------------------------
# Geometry — eval must reconstruct the renderer's exact crop window
# ---------------------------------------------------------------------------
def test_crop_geometry_matches_renderer():
    assert crop_geometry((9, 16), SRC_W, SRC_H) == (606, 1920, 1314)
    assert crop_geometry((1, 1), SRC_W, SRC_H) == (1080, 1080, 840)
    # 16:9 keeps the full width → no horizontal crop possible.
    assert crop_geometry((16, 9), SRC_W, SRC_H)[2] == 0


def test_crop_window_centered():
    seg = _seg(0, 10, (9, 16), 1, 0.5)
    left, right = _crop_window(seg, SRC_W, SRC_H, 5.0)
    assert abs(left - 657 / 1920) < 1e-6
    assert abs(right - 1263 / 1920) < 1e-6


def test_crop_window_full_width_when_no_crop():
    seg = _seg(0, 10, (16, 9), 1, 0.5)
    assert _crop_window(seg, SRC_W, SRC_H, 5.0) == (0.0, 1.0)


# ---------------------------------------------------------------------------
# Goal 1 — letterboxing / framing
# ---------------------------------------------------------------------------
def test_no_cut_full_containment():
    plan = [_seg(0, 10, (9, 16), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["letterbox"]["face_cut_rate"] == 0.0
    assert rep["letterbox"]["subject_containment"] == 1.0
    assert rep["letterbox"]["flag"] == "ok"


def test_face_cut_detected():
    # Framed face centered; a second detected face sits far right, outside the
    # 9:16 window (~[0.34, 0.66]) → it is cut.
    plan = [_seg(0, 10, (9, 16), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5), _tr(2, 0.95)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["letterbox"]["face_cut_rate"] == 1.0
    assert any(w["metric"] == "face_cut_rate" for w in rep["worst"])


def test_over_letterbox_flags_unneeded_bars():
    # Narrow subject but the plan letterboxed to 16:9 — a tighter rung (1:1)
    # would still have contained it.
    plan = [_seg(0, 10, (16, 9), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5, w=0.1)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["letterbox"]["over_letterbox_rate"] == 1.0
    assert any(w["metric"] == "over_letterbox_rate" for w in rep["worst"])


def test_not_over_letterbox_when_bars_needed():
    # Wide subject (span 0.5): the tighter 4:5 rung (cov 0.45) can't contain it,
    # so 1:1 letterbox is justified.
    plan = [_seg(0, 10, (1, 1), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5, w=0.5)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["letterbox"]["over_letterbox_rate"] == 0.0


def test_gemini_text_letterbox_not_counted_as_over():
    # Narrow subject in a 16:9 letterbox — geometrically a tighter rung fits, BUT
    # the bars are an intentional Gemini text verdict (preserving side graphics the
    # geometry can't see). Must NOT count as over-letterbox.
    frames = _frames([(t, [_tr(1, 0.5, w=0.1)]) for t in range(11)])
    by_source = _seg(0, 10, (16, 9), 1, 0.5, trace={"source": "gemini_text"})
    assert (
        evaluate([by_source], frames, [], [], SRC_W, SRC_H, 10.0)["letterbox"][
            "over_letterbox_rate"
        ]
        == 0.0
    )
    # Same geometry, but via a verdict field instead of the trace source.
    by_verdict = _seg(0, 10, (16, 9), 1, 0.5)
    by_verdict["escalate"] = {"verdict": {"action": "letterbox"}}
    assert (
        evaluate([by_verdict], frames, [], [], SRC_W, SRC_H, 10.0)["letterbox"][
            "over_letterbox_rate"
        ]
        == 0.0
    )


def test_mean_letterbox_pct():
    plan = [_seg(0, 10, (1, 1), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert abs(rep["letterbox"]["mean_letterbox_pct"] - (1 - 1080 / 1920)) < 0.005


# ---------------------------------------------------------------------------
# Goal 2 — talker (audio ↔ video)
# ---------------------------------------------------------------------------
def test_av_sync_positive_when_framed_mouth_moves_with_speech():
    # Framed face's mouth oscillates during speech [0,5] and is still after;
    # a second face is present (→ dialogue) with a constant mouth.
    rows = []
    for t in range(12):
        if t <= 5:
            m1 = 0.1 if t % 2 == 0 else 0.5  # moving
        else:
            m1 = 0.3  # still
        rows.append((t, [_tr(1, 0.5, mouth=m1), _tr(2, 0.55, mouth=0.2)]))
    plan = [_seg(0, 11, (1, 1), 1, 0.5)]
    rep = evaluate(
        plan, _frames(rows), [], [{"start_sec": 0, "end_sec": 5}], SRC_W, SRC_H, 11.0
    )
    assert rep["talker"] is not None
    assert rep["talker"]["av_sync_score"] > 0.3
    assert rep["talker"]["framed_speaker_active_rate"] > 0.0


def test_speaker_miss_when_off_frame_face_talks():
    # We frame a silent listener (track 1, left); the talker (track 2) is off to
    # the right, outside the 9:16 window, with a moving mouth, during speech.
    rows = []
    for t in range(11):
        m2 = 0.1 if t % 2 == 0 else 0.6  # off-frame talker moving
        rows.append((t, [_tr(1, 0.3, mouth=0.3), _tr(2, 0.92, mouth=m2)]))
    plan = [_seg(0, 10, (9, 16), 1, 0.3)]
    rep = evaluate(
        plan, _frames(rows), [], [{"start_sec": 0, "end_sec": 10}], SRC_W, SRC_H, 10.0
    )
    assert rep["talker"]["speaker_miss_rate"] > 0.0
    assert any(w["metric"] == "speaker_miss_rate" for w in rep["worst"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_empty_plan_returns_empty():
    assert evaluate([], [], [], [], SRC_W, SRC_H, 0.0) == {}


def test_no_audio_or_dialogue_nulls_talker():
    plan = [_seg(0, 10, (9, 16), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["talker"] is None
    assert "letterbox" in rep and rep["meta"]["has_speech"] is False


def test_tiny_background_face_not_counted_as_cut():
    # Framed subject centered; a *tiny* (w=0.03) face off-frame must NOT count —
    # it's a bystander, not a cut subject.
    plan = [_seg(0, 10, (9, 16), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5), _tr(2, 0.95, w=0.03)]) for t in range(11)])
    rep = evaluate(plan, frames, [], [], SRC_W, SRC_H, 10.0)
    assert rep["letterbox"]["face_cut_rate"] == 0.0
    # A prominent off-frame face (w=0.12) at the same spot *is* a cut.
    frames2 = _frames([(t, [_tr(1, 0.5), _tr(2, 0.95, w=0.12)]) for t in range(11)])
    rep2 = evaluate(plan, frames2, [], [], SRC_W, SRC_H, 10.0)
    assert rep2["letterbox"]["face_cut_rate"] == 1.0


def test_talker_null_below_min_dialogue_frames():
    # Only 3 multi-face frames → not enough signal → talker is null, not a verdict.
    rows = [(t, [_tr(1, 0.5, mouth=0.3), _tr(2, 0.55, mouth=0.2)]) for t in range(3)]
    plan = [_seg(0, 3, (1, 1), 1, 0.5)]
    rep = evaluate(
        plan, _frames(rows), [], [{"start_sec": 0, "end_sec": 3}], SRC_W, SRC_H, 3.0
    )
    assert rep["talker"] is None


def test_3x4_canvas_full_bleed_has_no_letterbox():
    # On a 3:4 canvas (1440 tall), a (3,4) plan is full-bleed → 0% letterbox.
    from reframe_plan import RUNGS_BY_CANVAS

    plan = [_seg(0, 10, (3, 4), 1, 0.5)]
    frames = _frames([(t, [_tr(1, 0.5)]) for t in range(11)])
    rep = evaluate(
        plan,
        frames,
        [],
        [],
        SRC_W,
        SRC_H,
        10.0,
        canvas_h=1440,
        rungs=RUNGS_BY_CANVAS["3:4"],
    )
    assert rep["letterbox"]["mean_letterbox_pct"] == 0.0
    assert all(s["letterbox_pct"] == 0.0 for s in rep["segments"])


def test_must_keep_width_from_detections():
    seg = _seg(0, 10, (1, 1), 1, 0.5)
    frames = _frames([(t, [_tr(1, 0.5, w=0.2)]) for t in range(11)])
    # span 0.2 + COVERAGE_MARGIN 0.04 = 0.24
    assert abs(_must_keep_width(seg, frames) - 0.24) < 1e-9


# ---------------------------------------------------------------------------
# Split layout (Phase 3): two stacked panels — both subjects framed
# ---------------------------------------------------------------------------


def _split_seg(start, end, t1, x1, t2, x2):
    return {
        "start": start,
        "end": end,
        "layout": "split",
        "inner_ar": None,
        "crops": [
            {
                "track_id": t1,
                "source": "split_top",
                "keypoints": [(start, x1, 0.5), (end, x1, 0.5)],
            },
            {
                "track_id": t2,
                "source": "split_bottom",
                "keypoints": [(start, x2, 0.5), (end, x2, 0.5)],
            },
        ],
        "reason": "split",
        "trace": {"trigger": "split", "source": "split"},
    }


class TestSplitEval:
    def _run(self, speech=None):
        plan = [_split_seg(0, 10, 1, 0.25, 2, 0.75)]
        osc = [0.1, 0.45, 0.1, 0.5][:]  # oscillating mouth → talking
        frames = []
        for t in range(10):
            m1 = osc[t % 4]
            frames.append(
                {
                    "time_sec": float(t),
                    "tracks": [_tr(1, 0.25, mouth=m1), _tr(2, 0.75, mouth=0.2)],
                }
            )
        return evaluate(plan, frames, [], speech or [], SRC_W, SRC_H, 10.0)

    def test_split_does_not_crash_and_has_no_letterbox(self):
        rep = self._run()
        assert rep["segments"][0]["inner_ar"] is None
        assert rep["segments"][0]["letterbox_pct"] == 0.0
        assert rep["segments"][0]["over_letterbox"] is False
        assert rep["letterbox"]["mean_letterbox_pct"] == 0.0

    def test_split_frames_both_subjects(self):
        rep = self._run()
        # Both panels contain their subject → nothing cut, full containment.
        assert rep["letterbox"]["face_cut_rate"] == 0.0
        assert rep["letterbox"]["subject_containment"] == 1.0

    def test_split_talker_active_and_no_miss(self):
        # Both speakers are on screen, so whoever talks is shown — never a "miss".
        rep = self._run(speech=[{"start_sec": 0, "end_sec": 10}])
        talker = rep["talker"]
        assert talker is not None
        assert talker["framed_speaker_active_rate"] > 0.5
        assert talker["speaker_miss_rate"] in (None, 0.0)
